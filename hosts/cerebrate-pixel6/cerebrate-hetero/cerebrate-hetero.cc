// cerebrate-hetero: heterogeneous TPU + GPU inference worker (Segmentation
// and Labeling Lane -- see design-notes/Cerebrate Pixel 6 — Segmentation and
// Labeling Lane.md). Serves one model as a pipeline of accelerator stages:
//   tpu+gpu  stage 1 on the Edge TPU (TFLite 2.16.1 + NNAPI delegate pinned to
//            google-edgetpu, NNAPI CPU fallback disallowed, fp16 relaxation),
//            stage 2 on the GPU (LiteRT 2.3 CompiledModel); stage-1 outputs
//            feed stage-2 inputs by byte size. Optionally holds a GPU-only
//            model of the same interface as a fallback: used if the TPU stage
//            fails to load, or for any request whose TPU stage fails.
//   gpu      one model on the GPU (LiteRT 2.3), at fp32 or fp16 + fp32
//            accumulation.
// TFLite 2.16 and LiteRT 2.3 export the same TfLite* C names; the TFLite
// library is loaded privately (dlopen RTLD_LOCAL, see tpu_stage.cc) and has
// no dynamic relocations against those names, so the two coexist.
//
// Usage:
//   cerebrate-hetero <port> tpu+gpu <libtensorflowlite_jni.so> <stage1.tflite>
//                    <stage2.tflite> <fp32|fp16acc32> [<fallback.tflite> <fp32|fp16acc32>]
//   cerebrate-hetero <port> gpu <model.tflite> <fp32|fp16acc32>
// Outputs are named from CEREBRATE_HETERO_OUTPUTS (comma-separated, in the
// GPU model's output order; default boxes,score,cls,coef,protos) and the
// input from CEREBRATE_HETERO_INPUT (default images). Every tensor is float32.
//
// Wire protocol: cerebrate-graph's, unchanged (see its header), so the same
// MLServer adapter and graph-client serve it. DONE carries
// "request_id=.. inference_us=.. handle_us=.. backend=.. tpu_us=.. gpu_us=.."
// -- every value an integer, as the shared protocol parser expects; backend:
// 1 = tpu+gpu, 2 = gpu-fallback (TPU configured but unavailable or failed),
// 3 = gpu (gpu mode).
// Same posture as its siblings: serial, one model per process, fixed port,
// SO_RCVTIMEO against dead peers, TCP_NODELAY, binds only after loading.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

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

extern "C" int tpu_init(const char* lib, const char* model_path, int fp16);
extern "C" size_t tpu_input_bytes();
extern "C" int tpu_num_outputs();
extern "C" size_t tpu_output_bytes(int k);
extern "C" int tpu_run(const void* in, void* const* outs);

#define FRAME_DATA 0
#define FRAME_DONE 1
#define FRAME_ERROR 2
#define DTYPE_FLOAT 1

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
  std::vector<std::vector<int64_t>> out_dims;
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
  m->in.resize(n_in); m->out.resize(n_out); m->in_bytes.resize(n_in); m->out_bytes.resize(n_out); m->out_dims.resize(n_out);
  for (int side = 0; side < 2; side++) {
    for (LiteRtParamIndex i = 0; i < (side ? n_out : n_in); i++) {
      LiteRtTensor t; LiteRtRankedTensorType type;
      if (side) LR("out tensor", LiteRtGetSignatureOutputTensorByIndex(sig, i, &t)); else LR("in tensor", LiteRtGetSignatureInputTensorByIndex(sig, i, &t));
      LR("type", LiteRtGetRankedTensorType(t, &type));
      size_t bytes = 4;
      for (unsigned d = 0; d < type.layout.rank; d++) {
        bytes *= type.layout.dimensions[d];
        if (side) m->out_dims[i].push_back(type.layout.dimensions[d]);
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

// Writes the inputs (src[i] -> input i), runs, and copies the outputs out
// with synchronizing locks. Returns 0 on success.
static int gpu_run(GpuModel* m, const std::vector<const void*>& src, std::vector<std::vector<char>>* outs) {
  for (size_t i = 0; i < m->in.size(); i++) {
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

static std::vector<std::string> split(const char* s) {
  std::vector<std::string> v; std::string cur;
  for (; *s; s++) { if (*s == ',') { v.push_back(cur); cur.clear(); } else cur.push_back(*s); }
  v.push_back(cur);
  return v;
}

int main(int argc, char** argv) {
  if (argc < 5) {
    fprintf(stderr,
            "usage: %s <port> tpu+gpu <libtensorflowlite_jni.so> <stage1.tflite> <stage2.tflite> <fp32|fp16acc32> [<fallback.tflite> <fp32|fp16acc32>]\n"
            "       %s <port> gpu <model.tflite> <fp32|fp16acc32>\n", argv[0], argv[0]);
    return 1;
  }
  int port = atoi(argv[1]);
  std::string mode = argv[2];
  signal(SIGPIPE, SIG_IGN);
  const char* in_env = getenv("CEREBRATE_HETERO_INPUT");
  std::string input_name = in_env && *in_env ? in_env : "images";
  const char* out_env = getenv("CEREBRATE_HETERO_OUTPUTS");
  std::vector<std::string> output_names = split(out_env && *out_env ? out_env : "boxes,score,cls,coef,protos");

  long load_t0 = now_us();
  LiteRtEnvironment env;
  if (LiteRtCreateEnvironment(0, NULL, &env) != kLiteRtStatusOk) { fprintf(stderr, "FATAL: LiteRT environment\n"); return 1; }
  GpuModel stage2, fallback;
  bool have_tpu = false, have_stage2 = false, have_fallback = false;
  std::vector<std::vector<char>> feat; std::vector<void*> feat_ptr; std::vector<int> stage2_from;
  std::string config;
  if (mode == "tpu+gpu" && argc >= 7) {
    if (tpu_init(argv[3], argv[4], 1) == 0) {
      have_tpu = true;
      feat.resize(tpu_num_outputs()); feat_ptr.resize(feat.size());
      for (size_t k = 0; k < feat.size(); k++) { feat[k].resize(tpu_output_bytes(k)); feat_ptr[k] = feat[k].data(); }
    } else {
      fprintf(stderr, "WARNING: TPU stage failed to load; serving from the fallback only\n");
    }
    if (have_tpu) {
      if (gpu_load(env, argv[5], argv[6], &stage2)) return 1;
      have_stage2 = true;
      for (size_t i = 0; i < stage2.in.size(); i++) {
        int from = -1;
        for (size_t k = 0; k < feat.size(); k++) if (feat[k].size() == stage2.in_bytes[i]) from = (int)k;
        if (from < 0) { fprintf(stderr, "FATAL: no TPU output matches stage-2 input %zu (%zu bytes)\n", i, stage2.in_bytes[i]); return 1; }
        stage2_from.push_back(from);
      }
    }
    if (argc >= 9) {
      if (gpu_load(env, argv[7], argv[8], &fallback)) return 1;
      have_fallback = true;
    }
    if (!have_tpu && !have_fallback) { fprintf(stderr, "FATAL: TPU stage unavailable and no fallback\n"); return 1; }
    config = std::string("tpu(fp16):") + argv[4] + " -> gpu(" + argv[6] + "):" + argv[5] +
             (have_fallback ? std::string(" | fallback gpu(") + argv[8] + "):" + argv[7] : "");
  } else if (mode == "gpu" && argc >= 5) {
    if (gpu_load(env, argv[3], argv[4], &fallback)) return 1;
    have_fallback = true;
    config = std::string("gpu(") + argv[4] + "):" + argv[3];
  } else {
    fprintf(stderr, "FATAL: bad arguments for mode %s\n", mode.c_str());
    return 1;
  }
  long load_us = now_us() - load_t0;
  GpuModel* out_model = have_stage2 ? &stage2 : &fallback;
  if (output_names.size() != out_model->out.size()) {
    fprintf(stderr, "FATAL: %zu output names for %zu outputs\n", output_names.size(), out_model->out.size());
    return 1;
  }
  size_t input_bytes = have_tpu ? tpu_input_bytes() : fallback.in_bytes[0];
  if (have_tpu && have_fallback && fallback.in_bytes[0] != input_bytes) {
    fprintf(stderr, "FATAL: fallback input (%zu bytes) differs from the TPU stage input (%zu bytes)\n", fallback.in_bytes[0], input_bytes);
    return 1;
  }

  std::string describe;
  {
    char buf[96];
    describe.append("{\"worker\":\"cerebrate-hetero\",\"mode\":");
    append_json_string(&describe, mode.c_str());
    describe.append(",\"config\":");
    append_json_string(&describe, config.c_str());
    snprintf(buf, sizeof(buf), ",\"tpu\":%s,\"fallback\":%s,\"load_us\":%ld,\"inputs\":[{\"name\":",
             have_tpu ? "true" : "false", have_fallback ? "true" : "false", load_us);
    describe.append(buf);
    append_json_string(&describe, input_name.c_str());
    snprintf(buf, sizeof(buf), ",\"dtype\":1,\"shape\":[1,640,640,3],\"bytes\":%zu}],\"outputs\":[", input_bytes);
    describe.append(buf);
    for (size_t k = 0; k < output_names.size(); k++) {
      if (k) describe.push_back(',');
      describe.append("{\"name\":"); append_json_string(&describe, output_names[k].c_str());
      describe.append(",\"dtype\":1,\"shape\":[");
      for (size_t d = 0; d < out_model->out_dims[k].size(); d++) {
        snprintf(buf, sizeof(buf), "%s%lld", d ? "," : "", (long long)out_model->out_dims[k][d]); describe.append(buf);
      }
      describe.append("]}");
    }
    describe.append("]}");
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
  fprintf(stderr, "READY worker=cerebrate-hetero mode=%s tpu=%d fallback=%d load_us=%ld port=%d config=%s\n",
          mode.c_str(), have_tpu, have_fallback, load_us, port, config.c_str());

  long request_id = 0;
  std::vector<std::vector<char>> outs;
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
      if (inputs.empty()) {
        if (send_frame(client, FRAME_DATA, describe.data(), describe.size()) != 0) break;
        char done[96]; snprintf(done, sizeof(done), "request_id=%ld inference_us=0 handle_us=%ld", request_id, now_us() - handle_t0);
        if (send_frame(client, FRAME_DONE, done, strlen(done)) != 0) break;
        continue;
      }
      if (inputs.size() != 1 || inputs[0].name != input_name || inputs[0].dtype != DTYPE_FLOAT || inputs[0].data.size() != input_bytes) {
        snprintf(err, sizeof(err), "expected one float32 input '%s' of %zu bytes", input_name.c_str(), input_bytes);
        if (send_error(client, err) != 0) break;
        continue;
      }
      long t0 = now_us(), tpu_us = 0, gpu_us = 0;
      int backend = 0;
      int ok = 0;
      if (have_tpu) {
        if (tpu_run(inputs[0].data.data(), feat_ptr.data()) == 0) {
          long t1 = now_us(); tpu_us = t1 - t0;
          std::vector<const void*> src;
          for (int from : stage2_from) src.push_back(feat[from].data());
          if (gpu_run(&stage2, src, &outs) == 0) { gpu_us = now_us() - t1; backend = 1; ok = 1; }
        } else {
          fprintf(stderr, "WARNING: request %ld: TPU stage failed\n", request_id);
        }
      }
      if (!ok && have_fallback) {
        long t1 = now_us();
        if (gpu_run(&fallback, {inputs[0].data.data()}, &outs) == 0) { gpu_us = now_us() - t1; backend = mode == "tpu+gpu" ? 2 : 3; ok = 1; }
      }
      long inference_us = now_us() - t0;
      if (!ok) { if (send_error(client, "inference failed on every configured backend") != 0) break; continue; }
      std::string payload;
      put_u32(&payload, (uint32_t)outs.size());
      for (size_t k = 0; k < outs.size(); k++) {
        put_u16(&payload, (uint16_t)output_names[k].size());
        payload.append(output_names[k]);
        payload.push_back((char)DTYPE_FLOAT);
        payload.push_back((char)out_model->out_dims[k].size());
        for (int64_t d : out_model->out_dims[k]) put_i64(&payload, d);
        put_u32(&payload, (uint32_t)outs[k].size());
        payload.append(outs[k].data(), outs[k].size());
      }
      if (send_frame(client, FRAME_DATA, payload.data(), payload.size()) != 0) break;
      char done[192];
      snprintf(done, sizeof(done), "request_id=%ld inference_us=%ld handle_us=%ld backend=%d tpu_us=%ld gpu_us=%ld",
               request_id, inference_us, now_us() - handle_t0, backend, tpu_us, gpu_us);
      if (send_frame(client, FRAME_DONE, done, strlen(done)) != 0) break;
    }
    close(client);
  }
  return 0;
}
