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
// Any number of input and output tensors: each line of inputs.txt is one
// sample, a comma-separated file per model input (in signature order). The
// first result for each sample is written to <out_dir>/<i>_o<k>.bin per output
// k for offline accuracy analysis, and output 0 is checked to differ across
// samples.
//
// usage: litert-e2e <model.tflite> <cpu|gpu|gpu+cpu> <req|host> <inputs.txt> <out_dir>
//                   <iterations> [sustain_seconds] [fp32|fp16|fp16acc32|default]
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
  // "gpu" = GPU only; "gpu+cpu" = GPU with CPU fallback for ops the GPU can't take.
  bool gpu = strncmp(argv[2], "gpu", 3) == 0;
  bool gpu_cpu = strcmp(argv[2], "gpu+cpu") == 0;
  bool req = strcmp(argv[3], "req") == 0;
  std::string out_dir = argv[5];
  int iterations = atoi(argv[6]);
  int sustain_s = argc > 7 ? atoi(argv[7]) : 0;
  const char* prec = argc > 8 ? argv[8] : "fp32";

  std::vector<std::vector<std::vector<char>>> inputs;  // [sample][input]
  {
    FILE* lst = fopen(argv[4], "r");
    if (!lst) { fprintf(stderr, "FATAL: cannot open %s\n", argv[4]); return 1; }
    char line[512];
    while (fgets(line, sizeof(line), lst)) {
      line[strcspn(line, "\r\n")] = 0;
      if (!line[0]) continue;
      std::vector<std::vector<char>> sample;
      for (char* tok = strtok(line, ","); tok; tok = strtok(NULL, ",")) {
        FILE* f = fopen(tok, "rb");
        if (!f) { fprintf(stderr, "FATAL: cannot open %s\n", tok); return 1; }
        fseek(f, 0, SEEK_END);
        long n = ftell(f);
        fseek(f, 0, SEEK_SET);
        std::vector<char> buf(n);
        if (fread(buf.data(), 1, n, f) != (size_t)n) { fprintf(stderr, "FATAL: short read %s\n", tok); return 1; }
        fclose(f);
        sample.push_back(buf);
      }
      inputs.push_back(sample);
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
                               options, gpu_cpu ? (LiteRtHwAcceleratorSet)(kLiteRtHwAcceleratorGpu | kLiteRtHwAcceleratorCpu)
                                     : gpu ? kLiteRtHwAcceleratorGpu : kLiteRtHwAcceleratorCpu));
  if (gpu && strcmp(prec, "default") != 0) {
    LrtGpuOptions* g;
    CHECK("LrtCreateGpuOptions", LrtCreateGpuOptions(&g));
    LiteRtDelegatePrecision dp = strcmp(prec, "fp16") == 0       ? kLiteRtDelegatePrecisionFp16
                                 : strcmp(prec, "fp16acc32") == 0 ? kLiteRtDelegatePrecisionFp16WithFp32Accum
                                                                  : kLiteRtDelegatePrecisionFp32;
    CHECK("SetPrecision", LrtSetGpuAcceleratorCompilationOptionsPrecision(g, dp));
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
  LiteRtParamIndex n_in = 0, n_out = 0;
  CHECK("NumInputs", LiteRtGetNumSignatureInputs(sig, &n_in));
  CHECK("NumOutputs", LiteRtGetNumSignatureOutputs(sig, &n_out));
  std::vector<LiteRtRankedTensorType> in_types(n_in), out_types(n_out);
  std::vector<size_t> in_sizes(n_in), out_sizes(n_out);
  std::vector<LiteRtTensorBuffer> in_bufs(n_in), out_bufs(n_out);
  for (int side = 0; side < 2; side++) {
    LiteRtParamIndex n = side ? n_out : n_in;
    for (LiteRtParamIndex i = 0; i < n; i++) {
      LiteRtTensor t;
      LiteRtRankedTensorType* type = side ? &out_types[i] : &in_types[i];
      if (side) CHECK("OutTensor", LiteRtGetSignatureOutputTensorByIndex(sig, i, &t));
      else CHECK("InTensor", LiteRtGetSignatureInputTensorByIndex(sig, i, &t));
      CHECK("TensorType", LiteRtGetRankedTensorType(t, type));
      size_t size = 4;
      for (unsigned d = 0; d < type->layout.rank; d++) size *= type->layout.dimensions[d];
      (side ? out_sizes : in_sizes)[i] = size;
      LiteRtTensorBuffer* buf = side ? &out_bufs[i] : &in_bufs[i];
      if (req) {
        LiteRtTensorBufferRequirements r;
        if (side) CHECK("OutRequirements", LiteRtGetCompiledModelOutputBufferRequirements(compiled, 0, i, &r));
        else CHECK("InRequirements", LiteRtGetCompiledModelInputBufferRequirements(compiled, 0, i, &r));
        CHECK("CreateFromRequirements", LiteRtCreateManagedTensorBufferFromRequirements(env, type, r, buf));
      } else {
        void* h;
        if (posix_memalign(&h, 64, size + 256)) return 1;
        CHECK("HostBuffer", LiteRtCreateTensorBufferFromHostMemory(type, h, size, NULL, buf));
      }
      LiteRtTensorBufferType bt;
      LiteRtGetTensorBufferType(*buf, &bt);
      printf("  %s %u: %zu bytes, buffer type %d\n", side ? "output" : "input", (unsigned)i, size, (int)bt);
    }
  }
  for (auto& sample : inputs) {
    if (sample.size() != n_in) { fprintf(stderr, "FATAL: sample has %zu files, model has %u inputs\n", sample.size(), (unsigned)n_in); return 1; }
    for (size_t i = 0; i < n_in; i++)
      if (sample[i].size() != in_sizes[i]) { fprintf(stderr, "FATAL: input %zu is %zu bytes, model wants %zu\n", i, sample[i].size(), in_sizes[i]); return 1; }
  }
  printf("model=%s accel=%s buffers=%s precision=%s compile_us=%ld inputs=%u outputs=%u samples=%zu\n",
         model_path, argv[2], req ? "req" : "host", gpu ? prec : "-", compile_us,
         (unsigned)n_in, (unsigned)n_out, inputs.size());
  fflush(stdout);

  std::vector<std::vector<char>> out_host(n_out);
  for (size_t k = 0; k < n_out; k++) out_host[k].resize(out_sizes[k]);
  std::vector<double> first_sum(inputs.size(), NAN);
  std::vector<long> tw, tr, tx, tt;
  long t_start = now_us(), window_start = t_start;
  std::vector<long> window;
  int total_iters = sustain_s > 0 ? 1 << 30 : iterations;
  for (int k = 0; k < total_iters; k++) {
    size_t idx = (size_t)k % inputs.size();
    void* p;
    long t0 = now_us();
    for (size_t i = 0; i < n_in; i++) {
      CHECK("LockIn", LiteRtLockTensorBuffer(in_bufs[i], &p, kLiteRtTensorBufferLockModeWrite));
      memcpy(p, inputs[idx][i].data(), in_sizes[i]);
      CHECK("UnlockIn", LiteRtUnlockTensorBuffer(in_bufs[i]));
    }
    long t1 = now_us();
    CHECK("Run", LiteRtRunCompiledModel(compiled, 0, n_in, in_bufs.data(), n_out, out_bufs.data()));
    long t2 = now_us();
    for (size_t o = 0; o < n_out; o++) {
      LiteRtStatus ls = LiteRtLockTensorBuffer(out_bufs[o], &p, kLiteRtTensorBufferLockModeRead);
      if (ls != kLiteRtStatusOk) {  // report and zero-fill, so the other outputs can still be inspected
        if (k == 0) fprintf(stderr, "WARN: LockOut output %zu (status %d), zero-filled\n", o, (int)ls);
        memset(out_host[o].data(), 0, out_sizes[o]);
        continue;
      }
      memcpy(out_host[o].data(), p, out_sizes[o]);
      CHECK("UnlockOut", LiteRtUnlockTensorBuffer(out_bufs[o]));
    }
    long t3 = now_us();
    if (k >= (int)inputs.size()) {  // first pass over the inputs is warm-up
      tw.push_back(t1 - t0); tx.push_back(t2 - t1); tr.push_back(t3 - t2); tt.push_back(t3 - t0);
    }
    if (std::isnan(first_sum[idx])) {
      double s = 0;
      const float* o = (const float*)out_host[0].data();
      for (size_t i = 0; i < out_sizes[0] / 4; i++) s += o[i];
      first_sum[idx] = s;
      for (size_t o2 = 0; o2 < n_out; o2++) {
        std::string path = out_dir + "/" + std::to_string(idx) + "_o" + std::to_string(o2) + ".bin";
        FILE* f = fopen(path.c_str(), "wb");
        fwrite(out_host[o2].data(), 1, out_sizes[o2], f);
        fclose(f);
      }
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
