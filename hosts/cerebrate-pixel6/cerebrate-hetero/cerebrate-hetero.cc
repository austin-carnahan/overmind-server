// cerebrate-hetero: heterogeneous TPU + GPU inference worker (Segmentation
// and Labeling Lane -- see design-notes/Cerebrate Pixel 6 — Segmentation and
// Labeling Lane.md). Serves one model as
//   a pipeline  stage 1 on the Edge TPU (TFLite 2.16.1 + NNAPI delegate pinned
//               to google-edgetpu, NNAPI CPU fallback disallowed, fp16
//               relaxation, optional compilation cache), stage 2 on the GPU
//               (LiteRT 2.3 CompiledModel); stage-1 outputs feed stage-2
//               inputs by byte size. Optionally a GPU-only model of the same
//               interface as a fallback: used if the TPU stage fails to load,
//               or for any request whose TPU stage fails. Or the GPU-only
//               model alone.
//   + optionally a prompt model (GPU), run once per prompt against the
//               pipeline's outputs, which are cached per image: e.g. EdgeSAM's
//               box decoder against its image embedding.
// TFLite 2.16 and LiteRT 2.3 export the same TfLite* C names; the TFLite
// library is loaded privately (dlopen RTLD_LOCAL, see tpu_stage.cc) and has
// no dynamic relocations against those names, so the two coexist.
//
// Usage:
//   cerebrate-hetero <port> tpu+gpu <libtensorflowlite_jni.so> <stage1.tflite>
//                    <stage2.tflite> <fp32|fp16acc32> [<fallback.tflite> <fp32|fp16acc32>]
//   cerebrate-hetero <port> gpu <model.tflite> <fp32|fp16acc32>
//   cerebrate-hetero <port> --config <file>
// The config file (key=value lines, # comments) holds everything the
// positional forms do and more:
//   input=image                      pipeline input name (default images)
//   outputs=image_embeddings         pipeline output names, in the final GPU
//                                    model's output order
//   tflite_lib=..., tpu=...          TPU stage (stage 1)
//   nnapi_cache_dir=...              NNAPI compilation cache for the TPU stage;
//                                    token = model file name + FNV-1a 64 of its
//                                    contents + "fp16r-tflite2.16.1"
//   stage2=..., stage2_precision=fp32|fp16acc32
//   fallback=..., fallback_precision=...
//   prompt_model=..., prompt_precision=...
//   prompt_inputs=<name>=<source>,... one per prompt-model input, in its
//                                    signature order; source pipeline:<output>,
//                                    request:<request tensor name> (stacked
//                                    along a leading prompt dimension), or
//                                    file:<path> (constant, read once)
//   prompt_outputs=mask_logits,iou   names of the prompt model's outputs
//   cache_entries=4                  pipeline results kept per image_id (LRU)
//   tpu_lock=<path>                  flock() held around each TPU run, to
//                                    serialize the TPU among workers that share
//                                    the path (bounded contention); optional
// Positional forms take CEREBRATE_HETERO_INPUT (default images) and
// CEREBRATE_HETERO_OUTPUTS (default boxes,score,cls,coef,protos).
//
// Requests (wire protocol: cerebrate-graph's, unchanged, so the same MLServer
// adapter and graph-client serve it):
//   {input}                     run the pipeline, return its outputs
//   {input, image_id}           (prompt model configured) run the pipeline and
//                               cache its outputs under image_id (int64, one
//                               element); returns image_id
//   {input, image_id?, prompts} run the pipeline, then the prompt model once
//                               per prompt; returns the prompt outputs stacked
//                               [N, ...]
//   {image_id, prompts}         the same against the cached pipeline outputs
//                               (ERROR if not cached: resend the image)
//   {}                          DESCRIBE: configuration and health as JSON
// DESCRIBE reports "model" and "backend" as the MLServer graph adapter checks
// them: CEREBRATE_HETERO_MODEL and CEREBRATE_HETERO_PROFILE when set (by
// cerebrate-supervisor, from the slot's fixed profile), otherwise the TPU (or
// only GPU) model path and the mode. DONE carries
// "request_id inference_us handle_us backend tpu_us gpu_us prompts prompt_us
// cache" -- every value an integer, as the shared protocol parser expects;
// backend: 0 = none (prompts against the cache), 1 = tpu+gpu, 2 = gpu-fallback
// (TPU configured but unavailable or failed), 3 = gpu (GPU-only); cache: 0 =
// not used, 1 = stored, 2 = hit.
// Same posture as its siblings: serial, one model per process, fixed port,
// SO_RCVTIMEO against dead peers, TCP_NODELAY, binds only after loading
// (supervisor readiness = models compiled and ready to serve).
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#include <map>
#include <string>
#include <vector>

#include "litert/c/litert_common.h"
#include "litert/c/litert_compiled_model.h"
#include "litert/c/litert_environment.h"
#include "litert/c/litert_model.h"
#include "litert/c/litert_opaque_options.h"
#include "litert/c/litert_options.h"
#include "litert/c/litert_tensor_buffer.h"
#include "litert/c/litert_tensor_buffer_requirements.h"
#include "litert/c/options/litert_gpu_options.h"

extern "C" int tpu_init(const char* lib, const char* model_path, int fp16, const char* cache_dir, const char* model_token);
extern "C" size_t tpu_input_bytes();
extern "C" int tpu_input_dims(int64_t* dims, int max_rank);
extern "C" int tpu_num_outputs();
extern "C" size_t tpu_output_bytes(int k);
extern "C" int tpu_run(const void* in, void* const* outs);

#define FRAME_DATA 0
#define FRAME_DONE 1
#define FRAME_ERROR 2
#define DTYPE_FLOAT 1
#define DTYPE_INT64 7

static const uint32_t kMaxInputs = 16;
static const uint32_t kMaxNameLen = 256;
static const uint8_t kMaxRank = 8;
static const uint64_t kMaxTensorBytes = 64ull << 20;
static const uint64_t kMaxRequestBytes = 128ull << 20;

static long now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

// Bytes per element for the dtypes this worker carries; 0 = unsupported
// (strings, complex, and anything newer than this list).
static size_t element_size(int dtype) {
  switch (dtype) {
    case 1 /* float */: return 4;
    case 2: return 1;
    case 3: return 1;
    case 4: return 2;
    case 5: return 2;
    case 6: return 4;
    case 7: return 8;
    case 9: return 1;
    case 10: return 2;
    case 11: return 8;
    case 12: return 4;
    case 13: return 8;
    default: return 0;
  }
}

static int read_exact(int fd, void* buf, size_t len) {
  size_t got = 0;
  while (got < len) {
    ssize_t n = read(fd, (char*)buf + got, len - got);
    if (n <= 0) return -1;
    got += (size_t)n;
  }
  return 0;
}

static int write_all(int fd, const void* buf, size_t len) {
  size_t sent = 0;
  while (sent < len) {
    ssize_t n = write(fd, (const char*)buf + sent, len - sent);
    if (n <= 0) return -1;
    sent += (size_t)n;
  }
  return 0;
}

static void put_u16(std::string* out, uint16_t v) {
  uint16_t be = htons(v);
  out->append((const char*)&be, 2);
}

static void put_u32(std::string* out, uint32_t v) {
  uint32_t be = htonl(v);
  out->append((const char*)&be, 4);
}

static void put_i64(std::string* out, int64_t v) {
  uint64_t u = (uint64_t)v;
  unsigned char b[8];
  for (int i = 7; i >= 0; i--) { b[i] = (unsigned char)(u & 0xff); u >>= 8; }
  out->append((const char*)b, 8);
}

static int read_u16(int fd, uint16_t* v) {
  uint16_t be;
  if (read_exact(fd, &be, 2) != 0) return -1;
  *v = ntohs(be);
  return 0;
}

static int read_u32(int fd, uint32_t* v) {
  uint32_t be;
  if (read_exact(fd, &be, 4) != 0) return -1;
  *v = ntohl(be);
  return 0;
}

static int read_i64(int fd, int64_t* v) {
  unsigned char b[8];
  if (read_exact(fd, b, 8) != 0) return -1;
  uint64_t u = 0;
  for (int i = 0; i < 8; i++) u = (u << 8) | b[i];
  *v = (int64_t)u;
  return 0;
}

static int send_frame(int fd, uint8_t type, const void* payload, size_t len) {
  unsigned char header[5];
  header[0] = type;
  uint32_t be = htonl((uint32_t)len);
  memcpy(header + 1, &be, 4);
  if (write_all(fd, header, 5) != 0) return -1;
  if (len > 0 && write_all(fd, payload, len) != 0) return -1;
  return 0;
}

static int send_error(int fd, const char* msg) {
  return send_frame(fd, FRAME_ERROR, msg, strlen(msg));
}

struct InputTensor {
  std::string name;
  int dtype;
  std::vector<int64_t> dims;
  std::vector<unsigned char> data;
};

// Reads one request's tensors. Returns 0 on success; -1 if the connection
// dropped (nothing to reply to); -2 if the header was malformed, with a
// reason in `err` (reply, then close: framing can't be trusted after this).
static int read_request(int fd, std::vector<InputTensor>* inputs, char* err, size_t err_len) {
  uint32_t num_inputs;
  if (read_u32(fd, &num_inputs) != 0) return -1;
  if (num_inputs > kMaxInputs) {
    snprintf(err, err_len, "too many inputs: %u (max %u)", num_inputs, kMaxInputs);
    return -2;
  }
  uint64_t request_bytes = 0;
  inputs->resize(num_inputs);
  for (uint32_t i = 0; i < num_inputs; i++) {
    InputTensor* t = &(*inputs)[i];
    uint16_t name_len;
    if (read_u16(fd, &name_len) != 0) return -1;
    if (name_len == 0 || name_len > kMaxNameLen) {
      snprintf(err, err_len, "input %u: bad name length %u", i, name_len);
      return -2;
    }
    t->name.resize(name_len);
    if (read_exact(fd, &t->name[0], name_len) != 0) return -1;

    unsigned char dtype_rank[2];
    if (read_exact(fd, dtype_rank, 2) != 0) return -1;
    t->dtype = dtype_rank[0];
    uint8_t rank = dtype_rank[1];
    size_t elem = element_size(t->dtype);
    if (elem == 0) {
      snprintf(err, err_len, "input %s: unsupported dtype %d", t->name.c_str(), t->dtype);
      return -2;
    }
    if (rank > kMaxRank) {
      snprintf(err, err_len, "input %s: rank %u exceeds %u", t->name.c_str(), rank, kMaxRank);
      return -2;
    }
    t->dims.resize(rank);
    uint64_t count = 1;
    for (uint8_t d = 0; d < rank; d++) {
      if (read_i64(fd, &t->dims[d]) != 0) return -1;
      if (t->dims[d] < 0 || (uint64_t)t->dims[d] > kMaxTensorBytes) {
        snprintf(err, err_len, "input %s: bad dim %lld", t->name.c_str(), (long long)t->dims[d]);
        return -2;
      }
      count *= (uint64_t)t->dims[d];
      if (count > kMaxTensorBytes) {
        snprintf(err, err_len, "input %s: too many elements", t->name.c_str());
        return -2;
      }
    }
    uint32_t data_len;
    if (read_u32(fd, &data_len) != 0) return -1;
    uint64_t expected = count * elem;
    if (data_len != expected) {
      snprintf(err, err_len, "input %s: data_len %u, dims and dtype need %llu",
               t->name.c_str(), data_len, (unsigned long long)expected);
      return -2;
    }
    if (expected > kMaxTensorBytes) {
      snprintf(err, err_len, "input %s: %llu bytes exceeds %llu", t->name.c_str(),
               (unsigned long long)expected, (unsigned long long)kMaxTensorBytes);
      return -2;
    }
    request_bytes += expected;
    if (request_bytes > kMaxRequestBytes) {
      snprintf(err, err_len, "request exceeds %llu bytes", (unsigned long long)kMaxRequestBytes);
      return -2;
    }
    t->data.resize(data_len);
    if (data_len > 0 && read_exact(fd, t->data.data(), data_len) != 0) return -1;
  }
  return 0;
}

static void append_json_string(std::string* out, const char* s) {
  out->push_back('"');
  for (; *s; s++) {
    unsigned char c = (unsigned char)*s;
    if (c == '"' || c == '\\') { out->push_back('\\'); out->push_back((char)c); }
    else if (c < 0x20) { char esc[8]; snprintf(esc, sizeof(esc), "\\u%04x", c); out->append(esc); }
    else out->push_back((char)c);
  }
  out->push_back('"');
}

// A model on the GPU: compiled once, with persistent requirement-based
// input/output buffers.
struct GpuModel {
  LiteRtCompiledModel compiled = nullptr;
  std::vector<LiteRtTensorBuffer> in, out;
  std::vector<size_t> in_bytes, out_bytes;
  std::vector<std::vector<int64_t>> in_dims, out_dims;
};

static int gpu_load(LiteRtEnvironment env, const char* path, const char* prec, GpuModel* m) {
#define LR(label, expr) do { LiteRtStatus s_ = (expr); if (s_ != kLiteRtStatusOk) { fprintf(stderr, "FATAL: %s %s (status %d)\n", path, label, (int)s_); return 1; } } while (0)
  LiteRtModel model; LR("model", LiteRtCreateModelFromFile(env, path, &model));
  LiteRtOptions options; LR("options", LiteRtCreateOptions(&options));
  LR("accelerators", LiteRtSetOptionsHardwareAccelerators(options, kLiteRtHwAcceleratorGpu));
  LrtGpuOptions* g; LR("gpu options", LrtCreateGpuOptions(&g));
  LR("precision", LrtSetGpuAcceleratorCompilationOptionsPrecision(
      g, strcmp(prec, "fp16acc32") == 0 ? kLiteRtDelegatePrecisionFp16WithFp32Accum : kLiteRtDelegatePrecisionFp32));
  const char* id; void* payload; void (*deleter)(void*);
  LR("opaque data", LrtGetOpaqueGpuOptionsData(g, &id, &payload, &deleter));
  LiteRtOpaqueOptions opaque; LR("opaque", LiteRtCreateOpaqueOptions(id, payload, deleter, &opaque));
  LR("add opaque", LiteRtAddOpaqueOptions(options, opaque)); LrtDestroyGpuOptions(g);
  LR("compile", LiteRtCreateCompiledModel(env, model, options, &m->compiled));
  LiteRtSignature sig; LR("signature", LiteRtGetModelSignature(model, 0, &sig));
  LiteRtParamIndex n_in = 0, n_out = 0;
  LR("inputs", LiteRtGetNumSignatureInputs(sig, &n_in)); LR("outputs", LiteRtGetNumSignatureOutputs(sig, &n_out));
  m->in.resize(n_in); m->out.resize(n_out); m->in_bytes.resize(n_in); m->out_bytes.resize(n_out);
  m->in_dims.resize(n_in); m->out_dims.resize(n_out);
  for (int side = 0; side < 2; side++) {
    for (LiteRtParamIndex i = 0; i < (side ? n_out : n_in); i++) {
      LiteRtTensor t; LiteRtRankedTensorType type;
      if (side) LR("out tensor", LiteRtGetSignatureOutputTensorByIndex(sig, i, &t)); else LR("in tensor", LiteRtGetSignatureInputTensorByIndex(sig, i, &t));
      LR("type", LiteRtGetRankedTensorType(t, &type));
      size_t bytes = 4;
      for (unsigned d = 0; d < type.layout.rank; d++) {
        bytes *= type.layout.dimensions[d];
        (side ? m->out_dims : m->in_dims)[i].push_back(type.layout.dimensions[d]);
      }
      LiteRtTensorBufferRequirements r;
      if (side) LR("out req", LiteRtGetCompiledModelOutputBufferRequirements(m->compiled, 0, i, &r));
      else LR("in req", LiteRtGetCompiledModelInputBufferRequirements(m->compiled, 0, i, &r));
      LR("buffer", LiteRtCreateManagedTensorBufferFromRequirements(env, &type, r, side ? &m->out[i] : &m->in[i]));
      (side ? m->out_bytes : m->in_bytes)[i] = bytes;
    }
  }
  return 0;
#undef LR
}

// Writes the inputs (src[i] -> input i; a null src[i] keeps what the buffer
// already holds), runs, and copies the outputs out with synchronizing locks.
// Returns 0 on success.
static int gpu_write_input(GpuModel* m, size_t i, const void* src) {
  void* p;
  if (LiteRtLockTensorBuffer(m->in[i], &p, kLiteRtTensorBufferLockModeWrite) != kLiteRtStatusOk) return 1;
  memcpy(p, src, m->in_bytes[i]);
  LiteRtUnlockTensorBuffer(m->in[i]);
  return 0;
}

static int gpu_run(GpuModel* m, const std::vector<const void*>& src, std::vector<std::vector<char>>* outs) {
  for (size_t i = 0; i < m->in.size(); i++) {
    if (!src[i]) continue;
    void* p;
    if (LiteRtLockTensorBuffer(m->in[i], &p, kLiteRtTensorBufferLockModeWrite) != kLiteRtStatusOk) return 1;
    memcpy(p, src[i], m->in_bytes[i]);
    LiteRtUnlockTensorBuffer(m->in[i]);
  }
  if (LiteRtRunCompiledModel(m->compiled, 0, m->in.size(), m->in.data(), m->out.size(), m->out.data()) != kLiteRtStatusOk) return 1;
  outs->resize(m->out.size());
  for (size_t k = 0; k < m->out.size(); k++) {
    void* p;
    if (LiteRtLockTensorBuffer(m->out[k], &p, kLiteRtTensorBufferLockModeRead) != kLiteRtStatusOk) return 1;
    (*outs)[k].assign((const char*)p, (const char*)p + m->out_bytes[k]);
    LiteRtUnlockTensorBuffer(m->out[k]);
  }
  return 0;
}

static std::vector<std::string> split(const std::string& s, char sep = ',') {
  std::vector<std::string> v; std::string cur;
  for (char c : s) { if (c == sep) { v.push_back(cur); cur.clear(); } else cur.push_back(c); }
  v.push_back(cur);
  return v;
}

static std::string trim(const std::string& s) {
  size_t a = s.find_first_not_of(" \t\r\n"), b = s.find_last_not_of(" \t\r\n");
  return a == std::string::npos ? "" : s.substr(a, b - a + 1);
}

static bool read_file(const std::string& path, std::vector<char>* buf) {
  FILE* f = fopen(path.c_str(), "rb");
  if (!f) return false;
  fseek(f, 0, SEEK_END);
  long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  buf->resize(n);
  bool ok = n == 0 || fread(buf->data(), 1, n, f) == (size_t)n;
  fclose(f);
  return ok;
}

// NNAPI compilation-cache token: a changed model file never reaches an old
// compiled blob (the G1 driver would reject a stale one anyway).
static std::string cache_token(const std::string& path) {
  std::vector<char> data;
  if (!read_file(path, &data)) return "";
  uint64_t h = 1469598103934665603ull;
  for (char c : data) { h ^= (unsigned char)c; h *= 1099511628211ull; }
  std::string base = path.substr(path.find_last_of('/') + 1);
  char buf[64];
  snprintf(buf, sizeof(buf), "-%016llx-fp16r-tflite2.16.1", (unsigned long long)h);
  return base + buf;
}

struct PromptInput {
  std::string name, source, ref;  // source: pipeline | request | file
  int pipeline_index = -1;
  std::vector<char> file_data;
};

struct Config {
  std::string mode;  // tpu+gpu | gpu
  std::string input = "images";
  std::vector<std::string> outputs;
  std::string tflite_lib, tpu, nnapi_cache_dir, tpu_lock;
  std::string stage2, stage2_precision = "fp32", fallback, fallback_precision = "fp32";
  std::string prompt_model, prompt_precision = "fp32";
  std::vector<PromptInput> prompt_inputs;
  std::vector<std::string> prompt_outputs;
  int cache_entries = 4;
};

static int parse_config(const char* path, Config* c) {
  FILE* f = fopen(path, "r");
  if (!f) { fprintf(stderr, "FATAL: cannot open config %s\n", path); return 1; }
  char line[4096];
  while (fgets(line, sizeof(line), f)) {
    std::string l = line;
    size_t hash = l.find('#');
    if (hash != std::string::npos) l = l.substr(0, hash);
    l = trim(l);
    if (l.empty()) continue;
    size_t eq = l.find('=');
    if (eq == std::string::npos) { fprintf(stderr, "FATAL: config line without '=': %s\n", l.c_str()); fclose(f); return 1; }
    std::string k = trim(l.substr(0, eq)), v = trim(l.substr(eq + 1));
    if (k == "input") c->input = v;
    else if (k == "outputs") c->outputs = split(v);
    else if (k == "tflite_lib") c->tflite_lib = v;
    else if (k == "tpu") c->tpu = v;
    else if (k == "nnapi_cache_dir") c->nnapi_cache_dir = v;
    else if (k == "tpu_lock") c->tpu_lock = v;
    else if (k == "stage2") c->stage2 = v;
    else if (k == "stage2_precision") c->stage2_precision = v;
    else if (k == "fallback") c->fallback = v;
    else if (k == "fallback_precision") c->fallback_precision = v;
    else if (k == "prompt_model") c->prompt_model = v;
    else if (k == "prompt_precision") c->prompt_precision = v;
    else if (k == "prompt_outputs") c->prompt_outputs = split(v);
    else if (k == "cache_entries") c->cache_entries = atoi(v.c_str());
    else if (k == "prompt_inputs") {
      for (const std::string& item : split(v)) {
        size_t e = item.find('='), colon = item.find(':', e == std::string::npos ? 0 : e);
        if (e == std::string::npos || colon == std::string::npos) { fprintf(stderr, "FATAL: prompt input '%s' is not name=source:ref\n", item.c_str()); fclose(f); return 1; }
        PromptInput p;
        p.name = trim(item.substr(0, e)); p.source = trim(item.substr(e + 1, colon - e - 1)); p.ref = trim(item.substr(colon + 1));
        if (p.source != "pipeline" && p.source != "request" && p.source != "file") { fprintf(stderr, "FATAL: prompt input %s: unknown source %s\n", p.name.c_str(), p.source.c_str()); fclose(f); return 1; }
        c->prompt_inputs.push_back(p);
      }
    } else { fprintf(stderr, "FATAL: unknown config key %s\n", k.c_str()); fclose(f); return 1; }
  }
  fclose(f);
  c->mode = c->tpu.empty() ? "gpu" : "tpu+gpu";
  return 0;
}

static bool valid_precision(const std::string& p) { return p == "fp32" || p == "fp16acc32"; }

struct CacheEntry {
  int64_t id;
  long last_use;
  std::vector<std::vector<char>> outs;
};

static void put_tensor(std::string* payload, const std::string& name, int dtype, const std::vector<int64_t>& dims, const char* data, size_t bytes) {
  put_u16(payload, (uint16_t)name.size());
  payload->append(name);
  payload->push_back((char)dtype);
  payload->push_back((char)dims.size());
  for (int64_t d : dims) put_i64(payload, d);
  put_u32(payload, (uint32_t)bytes);
  payload->append(data, bytes);
}

static void append_dims(std::string* out, const std::vector<int64_t>& dims) {
  char buf[32];
  out->push_back('[');
  for (size_t d = 0; d < dims.size(); d++) { snprintf(buf, sizeof(buf), "%s%lld", d ? "," : "", (long long)dims[d]); out->append(buf); }
  out->push_back(']');
}

int main(int argc, char** argv) {
  if (argc < 4) {
    fprintf(stderr,
            "usage: %s <port> tpu+gpu <libtensorflowlite_jni.so> <stage1.tflite> <stage2.tflite> <fp32|fp16acc32> [<fallback.tflite> <fp32|fp16acc32>]\n"
            "       %s <port> gpu <model.tflite> <fp32|fp16acc32>\n"
            "       %s <port> --config <file>\n", argv[0], argv[0], argv[0]);
    return 1;
  }
  int port = atoi(argv[1]);
  signal(SIGPIPE, SIG_IGN);
  Config cfg;
  if (strcmp(argv[2], "--config") == 0) {
    if (parse_config(argv[3], &cfg)) return 1;
  } else {
    const char* in_env = getenv("CEREBRATE_HETERO_INPUT");
    const char* out_env = getenv("CEREBRATE_HETERO_OUTPUTS");
    if (in_env && *in_env) cfg.input = in_env;
    cfg.outputs = split(out_env && *out_env ? out_env : "boxes,score,cls,coef,protos");
    cfg.mode = argv[2];
    if (cfg.mode == "tpu+gpu" && argc >= 7) {
      cfg.tflite_lib = argv[3]; cfg.tpu = argv[4]; cfg.stage2 = argv[5]; cfg.stage2_precision = argv[6];
      if (argc >= 9) { cfg.fallback = argv[7]; cfg.fallback_precision = argv[8]; }
    } else if (cfg.mode == "gpu" && argc >= 5) {
      cfg.fallback = argv[3]; cfg.fallback_precision = argv[4];
    } else {
      fprintf(stderr, "FATAL: bad arguments for mode %s\n", cfg.mode.c_str());
      return 1;
    }
  }
  if (cfg.mode == "tpu+gpu" && (cfg.tflite_lib.empty() || cfg.stage2.empty())) { fprintf(stderr, "FATAL: a TPU stage needs tflite_lib and stage2\n"); return 1; }
  if (cfg.mode == "gpu" && cfg.fallback.empty()) { fprintf(stderr, "FATAL: no TPU stage and no GPU model\n"); return 1; }
  for (const std::string* p : {&cfg.stage2_precision, &cfg.fallback_precision, &cfg.prompt_precision})
    if (!valid_precision(*p)) { fprintf(stderr, "FATAL: precision %s (fp32 or fp16acc32)\n", p->c_str()); return 1; }
  if (cfg.cache_entries < 1) cfg.cache_entries = 1;

  long load_t0 = now_us();
  LiteRtEnvironment env;
  if (LiteRtCreateEnvironment(0, NULL, &env) != kLiteRtStatusOk) { fprintf(stderr, "FATAL: LiteRT environment\n"); return 1; }
  GpuModel stage2, fallback, prompt;
  bool have_tpu = false, have_stage2 = false, have_fallback = false, have_prompt = !cfg.prompt_model.empty();
  std::vector<std::vector<char>> feat; std::vector<void*> feat_ptr; std::vector<int> stage2_from;
  std::vector<int64_t> input_dims;
  std::string config_desc, token;
  long tpu_load_us = 0;
  if (cfg.mode == "tpu+gpu") {
    if (!cfg.nnapi_cache_dir.empty()) {
      mkdir(cfg.nnapi_cache_dir.c_str(), 0777);  // one level; NNAPI writes nothing into a missing directory
      token = cache_token(cfg.tpu);  // empty if unreadable: the load below fails too
    }
    long t = now_us();
    bool readable = cfg.nnapi_cache_dir.empty() || !token.empty();
    if (readable && tpu_init(cfg.tflite_lib.c_str(), cfg.tpu.c_str(), 1, token.empty() ? NULL : cfg.nnapi_cache_dir.c_str(), token.empty() ? NULL : token.c_str()) == 0) {
      have_tpu = true; tpu_load_us = now_us() - t;
      feat.resize(tpu_num_outputs()); feat_ptr.resize(feat.size());
      for (size_t k = 0; k < feat.size(); k++) { feat[k].resize(tpu_output_bytes(k)); feat_ptr[k] = feat[k].data(); }
      int64_t dims[8]; int rank = tpu_input_dims(dims, 8);
      input_dims.assign(dims, dims + rank);
    } else {
      fprintf(stderr, "WARNING: TPU stage failed to load; serving from the fallback only\n");
    }
    if (have_tpu) {
      if (gpu_load(env, cfg.stage2.c_str(), cfg.stage2_precision.c_str(), &stage2)) return 1;
      have_stage2 = true;
      for (size_t i = 0; i < stage2.in.size(); i++) {
        int from = -1;
        for (size_t k = 0; k < feat.size(); k++) if (feat[k].size() == stage2.in_bytes[i]) from = (int)k;
        if (from < 0) { fprintf(stderr, "FATAL: no TPU output matches stage-2 input %zu (%zu bytes)\n", i, stage2.in_bytes[i]); return 1; }
        stage2_from.push_back(from);
      }
    }
    if (!cfg.fallback.empty()) {
      if (gpu_load(env, cfg.fallback.c_str(), cfg.fallback_precision.c_str(), &fallback)) return 1;
      have_fallback = true;
    }
    if (!have_tpu && !have_fallback) { fprintf(stderr, "FATAL: TPU stage unavailable and no fallback\n"); return 1; }
    config_desc = "tpu(fp16" + std::string(token.empty() ? "" : ", cached") + "):" + cfg.tpu + " -> gpu(" + cfg.stage2_precision + "):" + cfg.stage2 +
                  (have_fallback ? " | fallback gpu(" + cfg.fallback_precision + "):" + cfg.fallback : "");
  } else {
    if (gpu_load(env, cfg.fallback.c_str(), cfg.fallback_precision.c_str(), &fallback)) return 1;
    have_fallback = true;
    config_desc = "gpu(" + cfg.fallback_precision + "):" + cfg.fallback;
  }
  GpuModel* out_model = have_stage2 ? &stage2 : &fallback;
  if (cfg.outputs.size() != out_model->out.size()) {
    fprintf(stderr, "FATAL: %zu output names for %zu outputs\n", cfg.outputs.size(), out_model->out.size());
    return 1;
  }
  if (have_stage2 && have_fallback) {
    for (size_t k = 0; k < stage2.out.size(); k++)
      if (k >= fallback.out.size() || fallback.out_bytes[k] != stage2.out_bytes[k]) { fprintf(stderr, "FATAL: fallback output %zu differs from the pipeline's\n", k); return 1; }
  }
  size_t input_bytes = have_tpu ? tpu_input_bytes() : fallback.in_bytes[0];
  if (!have_tpu) input_dims = fallback.in_dims[0];
  if (have_tpu && have_fallback && fallback.in_bytes[0] != input_bytes) {
    fprintf(stderr, "FATAL: fallback input (%zu bytes) differs from the TPU stage input (%zu bytes)\n", fallback.in_bytes[0], input_bytes);
    return 1;
  }
  if (have_prompt) {
    if (gpu_load(env, cfg.prompt_model.c_str(), cfg.prompt_precision.c_str(), &prompt)) return 1;
    if (cfg.prompt_inputs.size() != prompt.in.size()) { fprintf(stderr, "FATAL: %zu prompt inputs configured, the prompt model has %zu\n", cfg.prompt_inputs.size(), prompt.in.size()); return 1; }
    if (cfg.prompt_outputs.size() != prompt.out.size()) { fprintf(stderr, "FATAL: %zu prompt output names for %zu outputs\n", cfg.prompt_outputs.size(), prompt.out.size()); return 1; }
    for (size_t i = 0; i < cfg.prompt_inputs.size(); i++) {
      PromptInput& p = cfg.prompt_inputs[i];
      if (p.source == "pipeline") {
        for (size_t k = 0; k < cfg.outputs.size(); k++) if (cfg.outputs[k] == p.ref) p.pipeline_index = (int)k;
        if (p.pipeline_index < 0) { fprintf(stderr, "FATAL: prompt input %s: no pipeline output %s\n", p.name.c_str(), p.ref.c_str()); return 1; }
        if (out_model->out_bytes[p.pipeline_index] != prompt.in_bytes[i]) { fprintf(stderr, "FATAL: prompt input %s: pipeline output is %zu bytes, the model wants %zu\n", p.name.c_str(), out_model->out_bytes[p.pipeline_index], prompt.in_bytes[i]); return 1; }
      } else if (p.source == "file") {
        if (!read_file(p.ref, &p.file_data) || p.file_data.size() != prompt.in_bytes[i]) { fprintf(stderr, "FATAL: prompt input %s: %s missing or not %zu bytes\n", p.name.c_str(), p.ref.c_str(), prompt.in_bytes[i]); return 1; }
        // Constant: written into its resident input buffer once, here.
        if (gpu_write_input(&prompt, i, p.file_data.data())) { fprintf(stderr, "FATAL: prompt input %s: buffer write\n", p.name.c_str()); return 1; }
      }
    }
    config_desc += " ; prompts gpu(" + cfg.prompt_precision + "):" + cfg.prompt_model;
  }
  int lock_fd = -1;
  if (!cfg.tpu_lock.empty() && have_tpu) {
    lock_fd = open(cfg.tpu_lock.c_str(), O_CREAT | O_RDWR, 0666);
    if (lock_fd < 0) { fprintf(stderr, "FATAL: cannot open TPU lock %s\n", cfg.tpu_lock.c_str()); return 1; }
  }
  long load_us = now_us() - load_t0;

  // The static part of DESCRIBE; health is appended per request.
  std::string describe;
  {
    char buf[160];
    const char* model_env = getenv("CEREBRATE_HETERO_MODEL");
    const char* profile_env = getenv("CEREBRATE_HETERO_PROFILE");
    describe.append("{\"worker\":\"cerebrate-hetero\",\"model\":");
    append_json_string(&describe, model_env && *model_env ? model_env : (cfg.mode == "tpu+gpu" ? cfg.tpu : cfg.fallback).c_str());
    describe.append(",\"backend\":");
    append_json_string(&describe, profile_env && *profile_env ? profile_env : cfg.mode.c_str());
    describe.append(",\"mode\":");
    append_json_string(&describe, cfg.mode.c_str());
    describe.append(",\"config\":");
    append_json_string(&describe, config_desc.c_str());
    snprintf(buf, sizeof(buf), ",\"tpu\":%s,\"fallback\":%s,\"nnapi_cache\":%s,\"tpu_lock\":%s,\"load_us\":%ld,\"tpu_load_us\":%ld,\"inputs\":[{\"name\":",
             have_tpu ? "true" : "false", have_fallback ? "true" : "false", token.empty() ? "false" : "true", lock_fd >= 0 ? "true" : "false", load_us, tpu_load_us);
    describe.append(buf);
    append_json_string(&describe, cfg.input.c_str());
    describe.append(",\"dtype\":1,\"shape\":"); append_dims(&describe, input_dims);
    snprintf(buf, sizeof(buf), ",\"bytes\":%zu}", input_bytes); describe.append(buf);
    if (have_prompt) {
      describe.append(",{\"name\":\"image_id\",\"dtype\":7,\"shape\":[1]}");
      for (size_t i = 0; i < cfg.prompt_inputs.size(); i++) {
        if (cfg.prompt_inputs[i].source != "request") continue;
        describe.append(",{\"name\":"); append_json_string(&describe, cfg.prompt_inputs[i].ref.c_str());
        std::vector<int64_t> d = {-1}; d.insert(d.end(), prompt.in_dims[i].begin(), prompt.in_dims[i].end());
        describe.append(",\"dtype\":1,\"shape\":"); append_dims(&describe, d); describe.append("}");
      }
    }
    describe.append("],\"outputs\":[");
    for (size_t k = 0; k < cfg.outputs.size(); k++) {
      if (k) describe.push_back(',');
      describe.append("{\"name\":"); append_json_string(&describe, cfg.outputs[k].c_str());
      describe.append(",\"dtype\":1,\"shape\":"); append_dims(&describe, out_model->out_dims[k]); describe.append("}");
    }
    describe.append("]");
    if (have_prompt) {
      describe.append(",\"prompt_outputs\":[");
      for (size_t k = 0; k < cfg.prompt_outputs.size(); k++) {
        if (k) describe.push_back(',');
        describe.append("{\"name\":"); append_json_string(&describe, cfg.prompt_outputs[k].c_str());
        std::vector<int64_t> d = {-1}; d.insert(d.end(), prompt.out_dims[k].begin(), prompt.out_dims[k].end());
        describe.append(",\"dtype\":1,\"shape\":"); append_dims(&describe, d); describe.append("}");
      }
      snprintf(buf, sizeof(buf), "],\"cache_entries\":%d", cfg.cache_entries); describe.append(buf);
    }
  }

  int srv = socket(AF_INET, SOCK_STREAM, 0);
  int yes = 1;
  setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  struct sockaddr_in addr = {};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = INADDR_ANY;
  addr.sin_port = htons(port);
  if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) < 0) { perror("bind"); return 1; }
  listen(srv, 4);
  fprintf(stderr, "READY worker=cerebrate-hetero mode=%s tpu=%d fallback=%d prompts=%d load_us=%ld tpu_load_us=%ld port=%d config=%s\n",
          cfg.mode.c_str(), have_tpu, have_fallback, have_prompt, load_us, tpu_load_us, port, config_desc.c_str());

  // Health counters (DESCRIBE).
  long request_id = 0, pipeline_runs = 0, tpu_failures = 0, fallback_runs = 0, prompt_runs = 0, cache_hits = 0, cache_misses = 0, errors = 0;
  std::string last_error;
  std::vector<CacheEntry> cache;
  std::vector<std::vector<char>> outs, pouts;
  while (1) {
    int client = accept(srv, NULL, NULL);
    if (client < 0) continue;
    struct timeval recv_timeout = {30, 0};
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &recv_timeout, sizeof(recv_timeout));
    setsockopt(client, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes));
    while (1) {
      std::vector<InputTensor> inputs;
      char err[512];
      int r = read_request(client, &inputs, err, sizeof(err));
      if (r == -1) break;
      if (r == -2) { send_error(client, err); break; }
      request_id++;
      long handle_t0 = now_us();
      auto fail = [&](const char* msg) { errors++; last_error = msg; return send_error(client, msg); };
      if (inputs.empty()) {
        std::string d = describe;
        char buf[320];
        snprintf(buf, sizeof(buf), ",\"health\":{\"requests\":%ld,\"pipeline_runs\":%ld,\"tpu_failures\":%ld,\"fallback_runs\":%ld,\"prompt_runs\":%ld,"
                 "\"cache_hits\":%ld,\"cache_misses\":%ld,\"cached_images\":%zu,\"errors\":%ld,\"last_error\":",
                 request_id, pipeline_runs, tpu_failures, fallback_runs, prompt_runs, cache_hits, cache_misses, cache.size(), errors);
        d.append(buf); append_json_string(&d, last_error.c_str()); d.append("}}");
        if (send_frame(client, FRAME_DATA, d.data(), d.size()) != 0) break;
        char done[96]; snprintf(done, sizeof(done), "request_id=%ld inference_us=0 handle_us=%ld", request_id, now_us() - handle_t0);
        if (send_frame(client, FRAME_DONE, done, strlen(done)) != 0) break;
        continue;
      }
      // Route by input names.
      const InputTensor* image = nullptr; const InputTensor* image_id_t = nullptr;
      std::map<std::string, const InputTensor*> by_name;
      for (const InputTensor& t : inputs) by_name[t.name] = &t;
      if (by_name.size() != inputs.size()) { if (fail("duplicate input names") != 0) break; continue; }
      std::vector<const InputTensor*> prompt_src(cfg.prompt_inputs.size(), nullptr);
      size_t known = 0; int64_t n_prompts = -1; bool bad = false;
      if (by_name.count(cfg.input)) { image = by_name[cfg.input]; known++; }
      if (have_prompt && by_name.count("image_id")) { image_id_t = by_name["image_id"]; known++; }
      for (size_t i = 0; have_prompt && i < cfg.prompt_inputs.size(); i++) {
        const PromptInput& p = cfg.prompt_inputs[i];
        if (p.source != "request" || !by_name.count(p.ref)) continue;
        const InputTensor* t = by_name[p.ref]; known++;
        int64_t n = t->dims.empty() ? -1 : t->dims[0];
        if (t->dtype != DTYPE_FLOAT || n < 1 || t->data.size() != (size_t)n * prompt.in_bytes[i] || (n_prompts >= 0 && n != n_prompts)) {
          snprintf(err, sizeof(err), "prompt input '%s': float32 [N, ...] of N x %zu bytes, the same N for every prompt input", p.ref.c_str(), prompt.in_bytes[i]);
          bad = true; break;
        }
        n_prompts = n; prompt_src[i] = t;
      }
      if (!bad && known != inputs.size()) { snprintf(err, sizeof(err), "unknown input name(s); DESCRIBE lists the inputs"); bad = true; }
      if (!bad && n_prompts > 0)
        for (size_t i = 0; i < cfg.prompt_inputs.size(); i++)
          if (cfg.prompt_inputs[i].source == "request" && !prompt_src[i]) { snprintf(err, sizeof(err), "prompt input '%s' missing", cfg.prompt_inputs[i].ref.c_str()); bad = true; break; }
      if (!bad && image && (image->dtype != DTYPE_FLOAT || image->data.size() != input_bytes)) { snprintf(err, sizeof(err), "input '%s': float32 of %zu bytes", cfg.input.c_str(), input_bytes); bad = true; }
      if (!bad && image_id_t && (image_id_t->dtype != DTYPE_INT64 || image_id_t->data.size() != 8)) { snprintf(err, sizeof(err), "image_id: one int64"); bad = true; }
      if (!bad && !image && (n_prompts < 1 || !image_id_t)) { snprintf(err, sizeof(err), "send '%s', or image_id with prompts", cfg.input.c_str()); bad = true; }
      if (bad) { if (fail(err) != 0) break; continue; }
      int64_t image_id = 0;
      if (image_id_t) memcpy(&image_id, image_id_t->data.data(), 8);  // little-endian, as the protocol carries it

      long t0 = now_us(), tpu_us = 0, gpu_us = 0, prompt_us = 0;
      int backend = 0, cache_state = 0;
      const std::vector<std::vector<char>>* pipe = nullptr;
      if (image) {
        int ok = 0;
        if (have_tpu) {
          if (lock_fd >= 0) flock(lock_fd, LOCK_EX);
          int tr = tpu_run(image->data.data(), feat_ptr.data());
          if (lock_fd >= 0) flock(lock_fd, LOCK_UN);
          if (tr == 0) {
            long t1 = now_us(); tpu_us = t1 - t0;
            std::vector<const void*> src;
            for (int from : stage2_from) src.push_back(feat[from].data());
            if (gpu_run(&stage2, src, &outs) == 0) { gpu_us = now_us() - t1; backend = 1; ok = 1; }
          } else {
            tpu_failures++;
            fprintf(stderr, "WARNING: request %ld: TPU stage failed\n", request_id);
          }
        }
        if (!ok && have_fallback) {
          long t1 = now_us();
          if (gpu_run(&fallback, {image->data.data()}, &outs) == 0) { gpu_us = now_us() - t1; backend = cfg.mode == "tpu+gpu" ? 2 : 3; ok = 1; if (backend == 2) fallback_runs++; }
        }
        if (!ok) { if (fail("inference failed on every configured backend") != 0) break; continue; }
        pipeline_runs++;
        pipe = &outs;
        if (image_id_t) {
          size_t slot = cache.size();
          for (size_t c = 0; c < cache.size(); c++) if (cache[c].id == image_id) slot = c;
          if (slot == cache.size()) {
            if ((int)cache.size() < cfg.cache_entries) cache.push_back(CacheEntry());
            else { slot = 0; for (size_t c = 1; c < cache.size(); c++) if (cache[c].last_use < cache[slot].last_use) slot = c; }
          }
          cache[slot].id = image_id; cache[slot].last_use = now_us(); cache[slot].outs = outs;
          cache_state = 1;
        }
      } else {
        for (CacheEntry& c : cache) if (c.id == image_id) { pipe = &c.outs; c.last_use = now_us(); }
        if (!pipe) {
          cache_misses++;
          snprintf(err, sizeof(err), "image_id %lld not cached; send the image again", (long long)image_id);
          if (fail(err) != 0) break;
          continue;
        }
        cache_hits++; cache_state = 2;
      }

      std::string payload;
      if (n_prompts > 0) {
        long tp = now_us();
        std::vector<std::string> stacked(prompt.out.size());
        bool ok = true;
        for (int64_t n = 0; n < n_prompts && ok; n++) {
          // Constants stay resident from load; pipeline outputs are written
          // for the first prompt of the request only.
          std::vector<const void*> src(cfg.prompt_inputs.size(), nullptr);
          for (size_t i = 0; i < cfg.prompt_inputs.size(); i++) {
            const PromptInput& p = cfg.prompt_inputs[i];
            if (p.source == "pipeline" && n == 0) src[i] = (*pipe)[p.pipeline_index].data();
            else if (p.source == "request") src[i] = prompt_src[i]->data.data() + (size_t)n * prompt.in_bytes[i];
          }
          ok = gpu_run(&prompt, src, &pouts) == 0;
          for (size_t k = 0; ok && k < pouts.size(); k++) stacked[k].append(pouts[k].data(), pouts[k].size());
        }
        if (!ok) { if (fail("prompt model failed") != 0) break; continue; }
        prompt_runs += n_prompts;
        prompt_us = now_us() - tp;
        put_u32(&payload, (uint32_t)stacked.size());
        for (size_t k = 0; k < stacked.size(); k++) {
          std::vector<int64_t> d = {n_prompts}; d.insert(d.end(), prompt.out_dims[k].begin(), prompt.out_dims[k].end());
          put_tensor(&payload, cfg.prompt_outputs[k], DTYPE_FLOAT, d, stacked[k].data(), stacked[k].size());
        }
      } else if (have_prompt && image_id_t) {
        put_u32(&payload, 1);
        put_tensor(&payload, "image_id", DTYPE_INT64, {1}, (const char*)image_id_t->data.data(), 8);
      } else {
        put_u32(&payload, (uint32_t)pipe->size());
        for (size_t k = 0; k < pipe->size(); k++)
          put_tensor(&payload, cfg.outputs[k], DTYPE_FLOAT, out_model->out_dims[k], (*pipe)[k].data(), (*pipe)[k].size());
      }
      long inference_us = now_us() - t0;
      if (send_frame(client, FRAME_DATA, payload.data(), payload.size()) != 0) break;
      char done[256];
      snprintf(done, sizeof(done), "request_id=%ld inference_us=%ld handle_us=%ld backend=%d tpu_us=%ld gpu_us=%ld prompts=%lld prompt_us=%ld cache=%d",
               request_id, inference_us, now_us() - handle_t0, backend, tpu_us, gpu_us, (long long)(n_prompts > 0 ? n_prompts : 0), prompt_us, cache_state);
      if (send_frame(client, FRAME_DONE, done, strlen(done)) != 0) break;
    }
    close(client);
  }
  return 0;
}
