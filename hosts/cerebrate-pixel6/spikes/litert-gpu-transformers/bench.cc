// End-to-end LiteRT CompiledModel benchmark (Segmentation and Labeling Lane,
// Step 2A): latency from input preparation through synchronized output on the
// host, across different real inputs, for model-required ("requirement")
// buffers versus plain host-memory buffers, plus a sustained-load mode.
//
// Each iteration takes the next input in rotation and times three phases:
//   write = Lock(input, write) + memcpy of the prepared input + Unlock
//   run   = LiteRtRunCompiledModel
//   read  = Lock(output, read) + memcpy out + Unlock   (the lock is the sync
//           point: the clock stops only once the result is on the host)
// The first output for each input is written to <out_dir>/<i>.bin for offline
// accuracy analysis, and outputs for different inputs are checked to differ.
//
// usage: litert-e2e <model.tflite> <cpu|gpu> <req|host> <inputs.txt> <out_dir>
//                   <iterations> [sustain_seconds] [fp32|fp16|default]
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <algorithm>
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

static long now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

#define CHECK(label, expr)                                            \
  do {                                                                \
    LiteRtStatus s_ = (expr);                                         \
    if (s_ != kLiteRtStatusOk) {                                      \
      fprintf(stderr, "FATAL: %s (status %d)\n", label, (int)s_);     \
      exit(1);                                                        \
    }                                                                 \
  } while (0)

static long pct(std::vector<long> v, double p) {
  std::sort(v.begin(), v.end());
  return v[(size_t)(p * (v.size() - 1))];
}

int main(int argc, char** argv) {
  if (argc < 7) {
    fprintf(stderr, "usage: %s <model> <cpu|gpu> <req|host> <inputs.txt> <out_dir> <iterations> [sustain_s] [fp32|fp16|default]\n", argv[0]);
    return 1;
  }
  const char* model_path = argv[1];
  bool gpu = strcmp(argv[2], "gpu") == 0;
  bool req = strcmp(argv[3], "req") == 0;
  std::string out_dir = argv[5];
  int iterations = atoi(argv[6]);
  int sustain_s = argc > 7 ? atoi(argv[7]) : 0;
  const char* prec = argc > 8 ? argv[8] : "fp32";

  std::vector<std::vector<char>> inputs;
  {
    FILE* lst = fopen(argv[4], "r");
    if (!lst) { fprintf(stderr, "FATAL: cannot open %s\n", argv[4]); return 1; }
    char line[512];
    while (fgets(line, sizeof(line), lst)) {
      line[strcspn(line, "\r\n")] = 0;
      if (!line[0]) continue;
      FILE* f = fopen(line, "rb");
      if (!f) { fprintf(stderr, "FATAL: cannot open %s\n", line); return 1; }
      fseek(f, 0, SEEK_END);
      long n = ftell(f);
      fseek(f, 0, SEEK_SET);
      std::vector<char> buf(n);
      if (fread(buf.data(), 1, n, f) != (size_t)n) { fprintf(stderr, "FATAL: short read %s\n", line); return 1; }
      fclose(f);
      inputs.push_back(buf);
    }
    fclose(lst);
  }

  LiteRtEnvironment env;
  CHECK("CreateEnvironment", LiteRtCreateEnvironment(0, NULL, &env));
  LiteRtModel model;
  CHECK("CreateModelFromFile", LiteRtCreateModelFromFile(env, model_path, &model));
  LiteRtOptions options;
  CHECK("CreateOptions", LiteRtCreateOptions(&options));
  CHECK("SetAccelerators", LiteRtSetOptionsHardwareAccelerators(
                               options, gpu ? kLiteRtHwAcceleratorGpu : kLiteRtHwAcceleratorCpu));
  if (gpu && strcmp(prec, "default") != 0) {
    LrtGpuOptions* g;
    CHECK("LrtCreateGpuOptions", LrtCreateGpuOptions(&g));
    CHECK("SetPrecision", LrtSetGpuAcceleratorCompilationOptionsPrecision(
                              g, strcmp(prec, "fp16") == 0 ? kLiteRtDelegatePrecisionFp16
                                                           : kLiteRtDelegatePrecisionFp32));
    const char* id; void* payload; void (*deleter)(void*);
    CHECK("GetOpaqueGpuOptionsData", LrtGetOpaqueGpuOptionsData(g, &id, &payload, &deleter));
    LiteRtOpaqueOptions opaque;
    CHECK("CreateOpaqueOptions", LiteRtCreateOpaqueOptions(id, payload, deleter, &opaque));
    CHECK("AddOpaqueOptions", LiteRtAddOpaqueOptions(options, opaque));
    LrtDestroyGpuOptions(g);
  }
  long c0 = now_us();
  LiteRtCompiledModel compiled;
  CHECK("CreateCompiledModel", LiteRtCreateCompiledModel(env, model, options, &compiled));
  long compile_us = now_us() - c0;

  LiteRtSignature sig;
  CHECK("GetModelSignature", LiteRtGetModelSignature(model, 0, &sig));
  LiteRtTensor in_t, out_t;
  CHECK("GetInputTensor", LiteRtGetSignatureInputTensorByIndex(sig, 0, &in_t));
  CHECK("GetOutputTensor", LiteRtGetSignatureOutputTensorByIndex(sig, 0, &out_t));
  LiteRtRankedTensorType in_type, out_type;
  CHECK("InType", LiteRtGetRankedTensorType(in_t, &in_type));
  CHECK("OutType", LiteRtGetRankedTensorType(out_t, &out_type));
  size_t in_size = 4, out_size = 4;
  for (unsigned i = 0; i < in_type.layout.rank; i++) in_size *= in_type.layout.dimensions[i];
  for (unsigned i = 0; i < out_type.layout.rank; i++) out_size *= out_type.layout.dimensions[i];
  for (auto& in : inputs)
    if (in.size() != in_size) { fprintf(stderr, "FATAL: input is %zu bytes, model wants %zu\n", in.size(), in_size); return 1; }

  LiteRtTensorBuffer in_buf, out_buf;
  if (req) {
    LiteRtTensorBufferRequirements in_req, out_req;
    CHECK("InRequirements", LiteRtGetCompiledModelInputBufferRequirements(compiled, 0, 0, &in_req));
    CHECK("OutRequirements", LiteRtGetCompiledModelOutputBufferRequirements(compiled, 0, 0, &out_req));
    CHECK("CreateIn", LiteRtCreateManagedTensorBufferFromRequirements(env, &in_type, in_req, &in_buf));
    CHECK("CreateOut", LiteRtCreateManagedTensorBufferFromRequirements(env, &out_type, out_req, &out_buf));
  } else {
    void *ih, *oh;
    if (posix_memalign(&ih, 64, in_size + 256) || posix_memalign(&oh, 64, out_size + 256)) return 1;
    CHECK("HostIn", LiteRtCreateTensorBufferFromHostMemory(&in_type, ih, in_size, NULL, &in_buf));
    CHECK("HostOut", LiteRtCreateTensorBufferFromHostMemory(&out_type, oh, out_size, NULL, &out_buf));
  }
  LiteRtTensorBufferType in_bt, out_bt;
  LiteRtGetTensorBufferType(in_buf, &in_bt);
  LiteRtGetTensorBufferType(out_buf, &out_bt);
  printf("model=%s accel=%s buffers=%s precision=%s compile_us=%ld in_type=%d out_type=%d inputs=%zu\n",
         model_path, gpu ? "gpu" : "cpu", req ? "req" : "host", gpu ? prec : "-", compile_us,
         (int)in_bt, (int)out_bt, inputs.size());
  fflush(stdout);

  std::vector<char> out_host(out_size);
  std::vector<double> first_sum(inputs.size(), NAN);
  std::vector<long> tw, tr, tx, tt;
  long t_start = now_us(), window_start = t_start;
  std::vector<long> window;
  int total_iters = sustain_s > 0 ? 1 << 30 : iterations;
  for (int k = 0; k < total_iters; k++) {
    size_t idx = (size_t)k % inputs.size();
    void* p;
    long t0 = now_us();
    CHECK("LockIn", LiteRtLockTensorBuffer(in_buf, &p, kLiteRtTensorBufferLockModeWrite));
    memcpy(p, inputs[idx].data(), in_size);
    CHECK("UnlockIn", LiteRtUnlockTensorBuffer(in_buf));
    long t1 = now_us();
    CHECK("Run", LiteRtRunCompiledModel(compiled, 0, 1, &in_buf, 1, &out_buf));
    long t2 = now_us();
    CHECK("LockOut", LiteRtLockTensorBuffer(out_buf, &p, kLiteRtTensorBufferLockModeRead));
    memcpy(out_host.data(), p, out_size);
    CHECK("UnlockOut", LiteRtUnlockTensorBuffer(out_buf));
    long t3 = now_us();
    if (k >= (int)inputs.size()) {  // first pass over the inputs is warm-up
      tw.push_back(t1 - t0); tx.push_back(t2 - t1); tr.push_back(t3 - t2); tt.push_back(t3 - t0);
    }
    if (std::isnan(first_sum[idx])) {
      double s = 0;
      const float* o = (const float*)out_host.data();
      for (size_t i = 0; i < out_size / 4; i++) s += o[i];
      first_sum[idx] = s;
      std::string path = out_dir + "/" + std::to_string(idx) + ".bin";
      FILE* f = fopen(path.c_str(), "wb");
      fwrite(out_host.data(), 1, out_size, f);
      fclose(f);
    }
    if (sustain_s > 0) {
      window.push_back(t3 - t0);
      if (t3 - window_start >= 10000000L) {
        printf("window t=%lds iters=%zu median_us=%ld p90_us=%ld\n", (t3 - t_start) / 1000000L,
               window.size(), pct(window, 0.5), pct(window, 0.9));
        fflush(stdout);
        window.clear();
        window_start = t3;
      }
      if (t3 - t_start >= (long)sustain_s * 1000000L) break;
    }
  }
  int distinct = 0;
  for (size_t i = 0; i < first_sum.size(); i++) {
    bool dup = false;
    for (size_t j = 0; j < i; j++) dup |= first_sum[i] == first_sum[j];
    distinct += !dup;
  }
  printf("outputs distinct across inputs: %d/%zu\n", distinct, first_sum.size());
  if (!tt.empty()) {
    long sum = 0;
    for (long t : tt) sum += t;
    printf("iters=%zu  total median=%ld p90=%ld us | write median=%ld | run median=%ld | read median=%ld | throughput=%.1f/s\n",
           tt.size(), pct(tt, 0.5), pct(tt, 0.9), pct(tw, 0.5), pct(tx, 0.5), pct(tr, 0.5),
           1e6 * tt.size() / (double)std::max(1L, sum));
  }
  return 0;
}
