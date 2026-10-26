// cerebrate-graph: general-purpose ONNX Runtime graph worker (Segmentation
// and Labeling Lane, Step 1 -- see
// design-notes/Cerebrate Pixel 6 — Segmentation and Labeling Lane.md).
//
// Sibling of cerebrate-infer, not a replacement: cerebrate-infer stays the
// production MobileNet/TFLite path. This worker loads one .onnx model ONCE
// with one execution provider chosen at launch, then serves requests one at
// a time: any set of named input tensors in, every output tensor back, plus
// timing. Same posture as its siblings -- serial, one model per process,
// fixed port, SO_RCVTIMEO against dead peers, no auth.
//
// Usage: cerebrate-graph <model.onnx> <backend> <port>
//   backend: cpu | nnapi | nnapi16 | xnnpack | webgpu
//     nnapi    NNAPI EP with NNAPI_FLAG_CPU_DISABLED: NNAPI's own slow
//              nnapi-reference device is off; nodes NNAPI can't take still
//              run on ORT's CPU EP (that is ORT partitioning, not fallback).
//     nnapi16  same, plus NNAPI_FLAG_USE_FP16 (lets float graphs try fp16).
//     xnnpack  XNNPACK EP. Known to crash on the quantized MobileNet canary
//              (onnxruntime-characterization spike); fp32 models untested.
//     webgpu   WebGPU EP (Dawn on Vulkan, the Mali GPU). Untested on the
//              Pixel; the same backend browser-perception uses in Chrome.
//
// Wire protocol (all integers big-endian):
//   request  := u32 num_inputs, then num_inputs x tensor
//               num_inputs == 0 is a DESCRIBE request (model metadata).
//   tensor   := u16 name_len, name, u8 dtype (ONNXTensorElementDataType),
//               u8 rank, rank x i64 dims, u32 data_len, data
//               (data is raw element bytes in host order -- little-endian
//               on every machine this runs on -- row-major, exactly
//               product(dims) x element_size bytes).
//   response := typed frames [u8 type][u32 len][payload], cerebrate-generate's
//               convention:
//     DATA  (0) one frame: u32 num_outputs + num_outputs x tensor, or for
//               DESCRIBE a UTF-8 JSON object.
//     DONE  (1) "request_id=.. inference_us=.. handle_us=.." -- terminal.
//     ERROR (2) failure description -- terminal, no DONE follows.
// A request whose header is malformed (bad rank, oversize, unknown dtype)
// gets an ERROR frame and the connection is closed, since framing can no
// longer be trusted. A request that is well-formed but fails in ORT (wrong
// input name, shape mismatch) gets an ERROR frame and the connection stays
// usable.
//
// Optional environment (for characterization runs launched by hand, not via
// cerebrate-supervisor):
//   CEREBRATE_GRAPH_VERBOSE=1    ORT verbose logging (node placement).
//   CEREBRATE_GRAPH_OPT_LEVEL=   0 disable | 1 basic | 2 extended | 99 all
//                                (default: ORT's own default, all).
//   CEREBRATE_GRAPH_THREADS=     intra-op threads (default 4: the two X1
//                                and two A76 cores, matching cerebrate-infer).
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

#include "onnxruntime_c_api.h"
#if defined(__ANDROID__)
#include "nnapi_provider_factory.h"
#endif

#define FRAME_DATA 0
#define FRAME_DONE 1
#define FRAME_ERROR 2

// Sanity guards on what a request may ask us to allocate. The largest
// planned input is a SAM encoder image, 1x3x1024x1024 fp32 = 12 MB.
static const uint32_t kMaxInputs = 16;
static const uint32_t kMaxNameLen = 256;
static const uint8_t kMaxRank = 8;
static const uint64_t kMaxTensorBytes = 64ull << 20;
static const uint64_t kMaxRequestBytes = 128ull << 20;

static const OrtApi* g_api = NULL;

static long now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

#define CHECK_FATAL(expr)                                                 \
  do {                                                                    \
    OrtStatus* status_ = (expr);                                          \
    if (status_ != NULL) {                                                \
      fprintf(stderr, "FATAL: %s -> %s\n", #expr,                         \
              g_api->GetErrorMessage(status_));                           \
      g_api->ReleaseStatus(status_);                                      \
      exit(1);                                                            \
    }                                                                     \
  } while (0)

// Bytes per element for the dtypes this worker carries; 0 = unsupported
// (strings, complex, and anything newer than this list).
static size_t element_size(int dtype) {
  switch (dtype) {
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT: return 4;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8: return 1;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT8: return 1;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT16: return 2;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT16: return 2;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32: return 4;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64: return 8;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL: return 1;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16: return 2;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_DOUBLE: return 8;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT32: return 4;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT64: return 8;
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

// One {"name","dtype","shape"} entry per model input/output. Symbolic or
// unknown dims are reported as -1, with the symbol in "dim_params".
static void describe_io(OrtSession* session, int is_input, OrtAllocator* allocator, std::string* out) {
  size_t n = 0;
  if (is_input) CHECK_FATAL(g_api->SessionGetInputCount(session, &n));
  else CHECK_FATAL(g_api->SessionGetOutputCount(session, &n));
  out->push_back('[');
  for (size_t i = 0; i < n; i++) {
    char* name = NULL;
    OrtTypeInfo* type_info = NULL;
    if (is_input) {
      CHECK_FATAL(g_api->SessionGetInputName(session, i, allocator, &name));
      CHECK_FATAL(g_api->SessionGetInputTypeInfo(session, i, &type_info));
    } else {
      CHECK_FATAL(g_api->SessionGetOutputName(session, i, allocator, &name));
      CHECK_FATAL(g_api->SessionGetOutputTypeInfo(session, i, &type_info));
    }
    if (i > 0) out->push_back(',');
    out->append("{\"name\":");
    append_json_string(out, name);

    const OrtTensorTypeAndShapeInfo* tensor_info = NULL;
    CHECK_FATAL(g_api->CastTypeInfoToTensorInfo(type_info, &tensor_info));
    if (tensor_info == NULL) {
      out->append(",\"dtype\":null,\"shape\":null}");
    } else {
      ONNXTensorElementDataType dtype;
      size_t rank = 0;
      CHECK_FATAL(g_api->GetTensorElementType(tensor_info, &dtype));
      CHECK_FATAL(g_api->GetDimensionsCount(tensor_info, &rank));
      std::vector<int64_t> dims(rank);
      std::vector<const char*> params(rank);
      CHECK_FATAL(g_api->GetDimensions(tensor_info, dims.data(), rank));
      CHECK_FATAL(g_api->GetSymbolicDimensions(tensor_info, params.data(), rank));
      char buf[64];
      snprintf(buf, sizeof(buf), ",\"dtype\":%d,\"shape\":[", (int)dtype);
      out->append(buf);
      for (size_t d = 0; d < rank; d++) {
        snprintf(buf, sizeof(buf), "%s%lld", d ? "," : "", (long long)dims[d]);
        out->append(buf);
      }
      out->append("],\"dim_params\":[");
      for (size_t d = 0; d < rank; d++) {
        if (d) out->push_back(',');
        append_json_string(out, params[d] ? params[d] : "");
      }
      out->append("]}");
    }
    g_api->ReleaseTypeInfo(type_info);
    CHECK_FATAL(g_api->AllocatorFree(allocator, name));
  }
  out->push_back(']');
}

static void configure_backend(OrtSessionOptions* options, const char* backend, int threads) {
  if (strcmp(backend, "cpu") == 0) {
    CHECK_FATAL(g_api->SetIntraOpNumThreads(options, threads));
  } else if (strcmp(backend, "nnapi") == 0 || strcmp(backend, "nnapi16") == 0) {
#if defined(__ANDROID__)
    uint32_t flags = NNAPI_FLAG_CPU_DISABLED;
    if (strcmp(backend, "nnapi16") == 0) flags |= NNAPI_FLAG_USE_FP16;
    CHECK_FATAL(g_api->SetIntraOpNumThreads(options, threads));
    CHECK_FATAL(OrtSessionOptionsAppendExecutionProvider_Nnapi(options, flags));
#else
    fprintf(stderr, "FATAL: backend %s is only available on Android\n", backend);
    exit(1);
#endif
  } else if (strcmp(backend, "xnnpack") == 0) {
    // ORT's guidance for XNNPACK: give the threads to the EP and keep the
    // session's own intra-op pool at 1, or the two pools compete for cores.
    CHECK_FATAL(g_api->SetIntraOpNumThreads(options, 1));
    char threads_str[16];
    snprintf(threads_str, sizeof(threads_str), "%d", threads);
    const char* keys[] = {"intra_op_num_threads"};
    const char* values[] = {threads_str};
    CHECK_FATAL(g_api->SessionOptionsAppendExecutionProvider(options, "XNNPACK", keys, values, 1));
  } else if (strcmp(backend, "webgpu") == 0) {
    // Dawn-backed WebGPU EP, compiled into the stock 1.30.0 Android AAR
    // (Vulkan on the Pixel's Mali GPU) and the macOS release (Metal).
    CHECK_FATAL(g_api->SetIntraOpNumThreads(options, threads));
    CHECK_FATAL(g_api->SessionOptionsAppendExecutionProvider(options, "WebGPU", NULL, NULL, 0));
  } else {
    fprintf(stderr, "FATAL: unknown backend %s (expected cpu|nnapi|nnapi16|xnnpack|webgpu)\n", backend);
    exit(1);
  }
}

// Runs one request and writes the DATA frame. On failure writes an ERROR
// frame instead and returns 1 (connection stays usable); returns -1 if the
// client went away mid-write.
static int run_request(int fd, OrtSession* session, const std::vector<std::string>& output_names,
                       std::vector<InputTensor>* inputs, long* inference_us) {
  OrtMemoryInfo* mem_info = NULL;
  CHECK_FATAL(g_api->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &mem_info));

  std::vector<OrtValue*> input_values;
  std::vector<const char*> input_names;
  int rc = 0;
  for (size_t i = 0; i < inputs->size(); i++) {
    InputTensor* t = &(*inputs)[i];
    OrtValue* value = NULL;
    OrtStatus* status = g_api->CreateTensorWithDataAsOrtValue(
        mem_info, t->data.data(), t->data.size(), t->dims.data(), t->dims.size(),
        (ONNXTensorElementDataType)t->dtype, &value);
    if (status != NULL) {
      char msg[512];
      snprintf(msg, sizeof(msg), "input %s: %s", t->name.c_str(), g_api->GetErrorMessage(status));
      g_api->ReleaseStatus(status);
      rc = send_error(fd, msg) == 0 ? 1 : -1;
      break;
    }
    input_values.push_back(value);
    input_names.push_back(t->name.c_str());
  }

  std::vector<const char*> out_names;
  for (size_t i = 0; i < output_names.size(); i++) out_names.push_back(output_names[i].c_str());
  std::vector<OrtValue*> outputs(output_names.size(), NULL);

  if (rc == 0) {
    long t0 = now_us();
    OrtStatus* status = g_api->Run(session, NULL, input_names.data(),
                                   (const OrtValue* const*)input_values.data(), input_values.size(),
                                   out_names.data(), out_names.size(), outputs.data());
    *inference_us = now_us() - t0;
    if (status != NULL) {
      char msg[1024];
      snprintf(msg, sizeof(msg), "Run: %s", g_api->GetErrorMessage(status));
      g_api->ReleaseStatus(status);
      rc = send_error(fd, msg) == 0 ? 1 : -1;
    }
  }

  if (rc == 0) {
    std::string payload;
    put_u32(&payload, (uint32_t)outputs.size());
    for (size_t i = 0; i < outputs.size() && rc == 0; i++) {
      OrtTensorTypeAndShapeInfo* info = NULL;
      CHECK_FATAL(g_api->GetTensorTypeAndShape(outputs[i], &info));
      ONNXTensorElementDataType dtype;
      size_t rank = 0, count = 0;
      CHECK_FATAL(g_api->GetTensorElementType(info, &dtype));
      CHECK_FATAL(g_api->GetDimensionsCount(info, &rank));
      CHECK_FATAL(g_api->GetTensorShapeElementCount(info, &count));
      std::vector<int64_t> dims(rank);
      CHECK_FATAL(g_api->GetDimensions(info, dims.data(), rank));
      g_api->ReleaseTensorTypeAndShapeInfo(info);

      size_t elem = element_size(dtype);
      if (elem == 0 || rank > kMaxRank) {
        char msg[256];
        snprintf(msg, sizeof(msg), "output %s: unsupported dtype %d or rank %zu",
                 output_names[i].c_str(), (int)dtype, rank);
        rc = send_error(fd, msg) == 0 ? 1 : -1;
        break;
      }
      void* data = NULL;
      CHECK_FATAL(g_api->GetTensorMutableData(outputs[i], &data));
      put_u16(&payload, (uint16_t)output_names[i].size());
      payload.append(output_names[i]);
      payload.push_back((char)dtype);
      payload.push_back((char)rank);
      for (size_t d = 0; d < rank; d++) put_i64(&payload, dims[d]);
      put_u32(&payload, (uint32_t)(count * elem));
      payload.append((const char*)data, count * elem);
    }
    if (rc == 0) rc = send_frame(fd, FRAME_DATA, payload.data(), payload.size()) == 0 ? 0 : -1;
  }

  for (size_t i = 0; i < outputs.size(); i++) {
    if (outputs[i]) g_api->ReleaseValue(outputs[i]);
  }
  for (size_t i = 0; i < input_values.size(); i++) g_api->ReleaseValue(input_values[i]);
  g_api->ReleaseMemoryInfo(mem_info);
  return rc;
}

int main(int argc, char** argv) {
  if (argc < 4) {
    fprintf(stderr, "usage: %s <model.onnx> <cpu|nnapi|nnapi16|xnnpack|webgpu> <port>\n", argv[0]);
    return 1;
  }
  const char* model_path = argv[1];
  const char* backend = argv[2];
  int port = atoi(argv[3]);
  signal(SIGPIPE, SIG_IGN);

  g_api = OrtGetApiBase()->GetApi(ORT_API_VERSION);
  if (!g_api) {
    fprintf(stderr, "FATAL: OrtGetApiBase()->GetApi() returned NULL\n");
    return 1;
  }

  const char* verbose = getenv("CEREBRATE_GRAPH_VERBOSE");
  OrtLoggingLevel log_level =
      (verbose && strcmp(verbose, "1") == 0) ? ORT_LOGGING_LEVEL_VERBOSE : ORT_LOGGING_LEVEL_WARNING;
  OrtEnv* env = NULL;
  CHECK_FATAL(g_api->CreateEnv(log_level, "cerebrate-graph", &env));

  int threads = 4;
  const char* threads_env = getenv("CEREBRATE_GRAPH_THREADS");
  if (threads_env && atoi(threads_env) > 0) threads = atoi(threads_env);

  // --- Load once ---
  OrtSessionOptions* options = NULL;
  CHECK_FATAL(g_api->CreateSessionOptions(&options));
  const char* opt_level = getenv("CEREBRATE_GRAPH_OPT_LEVEL");
  if (opt_level && opt_level[0]) {
    CHECK_FATAL(g_api->SetSessionGraphOptimizationLevel(options, (GraphOptimizationLevel)atoi(opt_level)));
  }
  configure_backend(options, backend, threads);

  long load_t0 = now_us();
  OrtSession* session = NULL;
  OrtStatus* status = g_api->CreateSession(env, model_path, options, &session);
  if (status != NULL) {
    fprintf(stderr, "FATAL: failed to load %s with backend %s: %s\n", model_path, backend,
            g_api->GetErrorMessage(status));
    g_api->ReleaseStatus(status);
    return 1;
  }
  long load_us = now_us() - load_t0;

  OrtAllocator* allocator = NULL;
  CHECK_FATAL(g_api->GetAllocatorWithDefaultOptions(&allocator));
  std::vector<std::string> output_names;
  size_t num_outputs = 0, num_inputs = 0;
  CHECK_FATAL(g_api->SessionGetOutputCount(session, &num_outputs));
  CHECK_FATAL(g_api->SessionGetInputCount(session, &num_inputs));
  for (size_t i = 0; i < num_outputs; i++) {
    char* name = NULL;
    CHECK_FATAL(g_api->SessionGetOutputName(session, i, allocator, &name));
    output_names.push_back(name);
    CHECK_FATAL(g_api->AllocatorFree(allocator, name));
  }

  // DESCRIBE response, built once: it can't change for this process.
  std::string describe;
  {
    char buf[64];
    describe.append("{\"model\":");
    append_json_string(&describe, model_path);
    describe.append(",\"backend\":");
    append_json_string(&describe, backend);
    describe.append(",\"ort_version\":");
    append_json_string(&describe, OrtGetApiBase()->GetVersionString());
    snprintf(buf, sizeof(buf), ",\"load_us\":%ld,\"threads\":%d,\"inputs\":", load_us, threads);
    describe.append(buf);
    describe_io(session, 1, allocator, &describe);
    describe.append(",\"outputs\":");
    describe_io(session, 0, allocator, &describe);
    describe.append("}");
  }

  // --- Bind only after the model is loaded, so cerebrate-supervisor's
  // readiness probe means "ready to serve", not "process exists". ---
  int srv = socket(AF_INET, SOCK_STREAM, 0);
  int yes = 1;
  setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  struct sockaddr_in addr = {};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = INADDR_ANY;
  addr.sin_port = htons(port);
  if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
    perror("bind");
    return 1;
  }
  listen(srv, 4);
  fprintf(stderr, "READY model=%s backend=%s inputs=%zu outputs=%zu load_us=%ld port=%d\n",
          model_path, backend, num_inputs, num_outputs, load_us, port);

  long request_id = 0;
  while (1) {
    int client = accept(srv, NULL, NULL);
    if (client < 0) continue;
    // Same dead-peer protection as cerebrate-infer (see its README): an AVF
    // guest restart can leave a connection ESTABLISHED forever, and this
    // worker is serial, so one wedged read would block every client.
    struct timeval recv_timeout = {30, 0};
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &recv_timeout, sizeof(recv_timeout));
    // Each response is several small writes (frame headers, DONE). With
    // Nagle on, they stall behind the client's delayed ACK: measured ~45ms
    // added to a 3.5ms MobileNet request over the AVF path.
    setsockopt(client, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes));

    while (1) {
      std::vector<InputTensor> inputs;
      char err[512];
      int r = read_request(client, &inputs, err, sizeof(err));
      if (r == -1) break;
      if (r == -2) {
        send_error(client, err);
        break;
      }
      request_id++;
      long handle_t0 = now_us();
      long inference_us = 0;
      int rc;
      if (inputs.empty()) {
        rc = send_frame(client, FRAME_DATA, describe.data(), describe.size()) == 0 ? 0 : -1;
      } else {
        rc = run_request(client, session, output_names, &inputs, &inference_us);
      }
      if (rc < 0) break;
      if (rc == 0) {
        char done[160];
        snprintf(done, sizeof(done), "request_id=%ld inference_us=%ld handle_us=%ld",
                 request_id, inference_us, now_us() - handle_t0);
        if (send_frame(client, FRAME_DONE, done, strlen(done)) != 0) break;
      }
    }
    close(client);
  }
  return 0;
}
