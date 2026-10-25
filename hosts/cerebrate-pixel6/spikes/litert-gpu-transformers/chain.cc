// Two LiteRT CompiledModels run as one connected pipeline, each with its own
// GPU precision (EfficientSAM3's split-precision vision: trunk FP32 -> neck
// FP16 + FP32 accumulation). One process, one environment; model A's single
// input comes from the file list, its output 0 feeds model B's single input.
//
// Each iteration takes the next input in rotation and times, synchronized:
//   write   = Lock(A input, write) + memcpy of the prepared input + Unlock
//   a       = Run(A)
//   handoff = host: Lock(A output 0, read) + memcpy into Lock(B input, write)
//             (the read lock is A's sync point);
//             shared: nothing -- A's output buffer is passed to B as its input
//   b       = Run(B)
//   read    = Lock(B outputs, read) + memcpy out + Unlock (the sync point)
// total = write through read: on the host, ready for the next stage. The
// first pass over the inputs is warm-up. B's outputs for each sample are
// written to <out_dir>/<i>_o<k>.bin (as litert-e2e) for accuracy analysis.
//
// usage: litert-chain <A.tflite> <A fp32|fp16|fp16acc32> <B.tflite> <B precision> <host|shared>
//                     <inputs.txt> <out_dir> <iterations>
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

struct Stage {
  LiteRtModel model;
  LiteRtCompiledModel compiled;
  std::vector<LiteRtTensorBuffer> in, out;
  std::vector<size_t> in_size, out_size;
  long compile_us;
};

// GPU-only compiled model at the given precision, with model-required buffers.
static Stage load(LiteRtEnvironment env, const char* path, const char* prec) {
  Stage s;
  CHECK("CreateModelFromFile", LiteRtCreateModelFromFile(env, path, &s.model));
  LiteRtOptions options;
  CHECK("CreateOptions", LiteRtCreateOptions(&options));
  CHECK("SetAccelerators", LiteRtSetOptionsHardwareAccelerators(options, kLiteRtHwAcceleratorGpu));
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
  long c0 = now_us();
  CHECK("CreateCompiledModel", LiteRtCreateCompiledModel(env, s.model, options, &s.compiled));
  s.compile_us = now_us() - c0;
  LiteRtSignature sig;
  CHECK("GetModelSignature", LiteRtGetModelSignature(s.model, 0, &sig));
  LiteRtParamIndex n_in = 0, n_out = 0;
  CHECK("NumInputs", LiteRtGetNumSignatureInputs(sig, &n_in));
  CHECK("NumOutputs", LiteRtGetNumSignatureOutputs(sig, &n_out));
  for (int side = 0; side < 2; side++) {
    LiteRtParamIndex n = side ? n_out : n_in;
    for (LiteRtParamIndex i = 0; i < n; i++) {
      LiteRtTensor t;
      LiteRtRankedTensorType type;
      if (side) CHECK("OutTensor", LiteRtGetSignatureOutputTensorByIndex(sig, i, &t));
      else CHECK("InTensor", LiteRtGetSignatureInputTensorByIndex(sig, i, &t));
      CHECK("TensorType", LiteRtGetRankedTensorType(t, &type));
      size_t size = 4;
      for (unsigned d = 0; d < type.layout.rank; d++) size *= type.layout.dimensions[d];
      LiteRtTensorBufferRequirements r;
      if (side) CHECK("OutRequirements", LiteRtGetCompiledModelOutputBufferRequirements(s.compiled, 0, i, &r));
      else CHECK("InRequirements", LiteRtGetCompiledModelInputBufferRequirements(s.compiled, 0, i, &r));
      LiteRtTensorBuffer buf;
      CHECK("CreateFromRequirements", LiteRtCreateManagedTensorBufferFromRequirements(env, &type, r, &buf));
      (side ? s.out : s.in).push_back(buf);
      (side ? s.out_size : s.in_size).push_back(size);
    }
  }
  printf("  %s (%s): %zu inputs, %zu outputs, compile_us=%ld\n", path, prec, s.in.size(), s.out.size(), s.compile_us);
  return s;
}

static void copy_in(LiteRtTensorBuffer b, const void* src, size_t n) {
  void* p;
  CHECK("LockIn", LiteRtLockTensorBuffer(b, &p, kLiteRtTensorBufferLockModeWrite));
  memcpy(p, src, n);
  CHECK("UnlockIn", LiteRtUnlockTensorBuffer(b));
}

static void copy_out(LiteRtTensorBuffer b, void* dst, size_t n) {
  void* p;
  CHECK("LockOut", LiteRtLockTensorBuffer(b, &p, kLiteRtTensorBufferLockModeRead));
  memcpy(dst, p, n);
  CHECK("UnlockOut", LiteRtUnlockTensorBuffer(b));
}

int main(int argc, char** argv) {
  if (argc < 9) {
    fprintf(stderr, "usage: %s <A.tflite> <A prec> <B.tflite> <B prec> <host|shared> <inputs.txt> <out_dir> <iterations>\n", argv[0]);
    return 1;
  }
  bool shared = strcmp(argv[5], "shared") == 0;
  std::string out_dir = argv[7];
  int iterations = atoi(argv[8]);

  std::vector<std::vector<char>> inputs;
  {
    FILE* lst = fopen(argv[6], "r");
    if (!lst) { fprintf(stderr, "FATAL: cannot open %s\n", argv[6]); return 1; }
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
      inputs.push_back(std::move(buf));
    }
    fclose(lst);
  }

  LiteRtEnvironment env;
  CHECK("CreateEnvironment", LiteRtCreateEnvironment(0, NULL, &env));
  Stage a = load(env, argv[1], argv[2]);
  Stage b = load(env, argv[3], argv[4]);
  if (a.in.size() != 1 || b.in.size() != 1 || a.out_size[0] != b.in_size[0]) {
    fprintf(stderr, "FATAL: A must have one input, B one input of A's output 0 size (%zu vs %zu)\n", a.out_size[0], b.in_size[0]);
    return 1;
  }
  for (auto& x : inputs)
    if (x.size() != a.in_size[0]) { fprintf(stderr, "FATAL: input is %zu bytes, A wants %zu\n", x.size(), a.in_size[0]); return 1; }
  if (shared) {  // A's output buffer becomes B's input buffer
    LiteRtTensorBufferType ta, tb;
    LiteRtGetTensorBufferType(a.out[0], &ta);
    LiteRtGetTensorBufferType(b.in[0], &tb);
    printf("  shared hand-off: A output buffer type %d, B input buffer type %d\n", (int)ta, (int)tb);
    b.in[0] = a.out[0];
  }
  printf("chain handoff=%s samples=%zu\n", shared ? "shared" : "host", inputs.size());
  fflush(stdout);

  std::vector<char> mid(a.out_size[0]);
  std::vector<std::vector<char>> out_host(b.out.size());
  for (size_t k = 0; k < b.out.size(); k++) out_host[k].resize(b.out_size[k]);
  std::vector<bool> saved(inputs.size(), false);
  std::vector<long> tw, ta, th, tb, tr, tt;
  for (int k = 0; k < iterations; k++) {
    size_t idx = (size_t)k % inputs.size();
    long t0 = now_us();
    copy_in(a.in[0], inputs[idx].data(), a.in_size[0]);
    long t1 = now_us();
    CHECK("RunA", LiteRtRunCompiledModel(a.compiled, 0, 1, a.in.data(), a.out.size(), a.out.data()));
    long t2 = now_us();
    if (!shared) {
      copy_out(a.out[0], mid.data(), a.out_size[0]);
      copy_in(b.in[0], mid.data(), b.in_size[0]);
    }
    long t3 = now_us();
    CHECK("RunB", LiteRtRunCompiledModel(b.compiled, 0, 1, b.in.data(), b.out.size(), b.out.data()));
    long t4 = now_us();
    for (size_t o = 0; o < b.out.size(); o++) copy_out(b.out[o], out_host[o].data(), b.out_size[o]);
    long t5 = now_us();
    if (k >= (int)inputs.size()) {
      tw.push_back(t1 - t0); ta.push_back(t2 - t1); th.push_back(t3 - t2); tb.push_back(t4 - t3); tr.push_back(t5 - t4); tt.push_back(t5 - t0);
    }
    if (!saved[idx]) {
      saved[idx] = true;
      for (size_t o = 0; o < b.out.size(); o++) {
        std::string path = out_dir + "/" + std::to_string(idx) + "_o" + std::to_string(o) + ".bin";
        FILE* f = fopen(path.c_str(), "wb");
        fwrite(out_host[o].data(), 1, b.out_size[o], f);
        fclose(f);
      }
    }
  }
  if (!tt.empty())
    printf("iters=%zu  total median=%ld p90=%ld us | write %ld | A run %ld | handoff %ld | B run %ld | read %ld\n",
           tt.size(), pct(tt, 0.5), pct(tt, 0.9), pct(tw, 0.5), pct(ta, 0.5), pct(th, 0.5), pct(tb, 0.5), pct(tr, 0.5));
  return 0;
}
