// YOLOE TPU+GPU pipeline, synchronized end to end in one process: the TPU
// stage (tpu_stage.cc: TFLite 2.16 + NNAPI -> Edge TPU, fp16 relaxation) runs
// the backbone + neck, then the head runs on the GPU via LiteRT 2.3
// CompiledModel (requirement-based buffers). Per iteration: image -> TPU
// input, invoke, features -> host -> GPU input buffers (matched by byte
// size), run, locked (synchronizing) output reads. Reports TPU-stage,
// GPU-stage and total medians; writes the first pass's head outputs.
//
// usage: yoloe-pipeline <libtensorflowlite_jni.so> <backbone.tflite> <head.tflite>
//          <fp32|fp16acc32> <images.txt> <out_dir> <iterations>
//   images.txt: one NHWC float32 image file per line
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

extern "C" int tpu_init(const char* lib, const char* model_path, int fp16);
extern "C" size_t tpu_input_bytes();
extern "C" int tpu_num_outputs();
extern "C" size_t tpu_output_bytes(int k);
extern "C" int tpu_run(const void* in, void* const* outs);

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
      return 1;                                                       \
    }                                                                 \
  } while (0)
static long median(std::vector<long> v) { std::sort(v.begin(), v.end()); return v.empty() ? -1 : v[v.size() / 2]; }
static bool read_file(const char* p, std::vector<char>* b) {
  FILE* f = fopen(p, "rb"); if (!f) return false;
  fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET); b->resize(n);
  bool ok = fread(b->data(), 1, n, f) == (size_t)n; fclose(f); return ok;
}

int main(int argc, char** argv) {
  if (argc < 8) { fprintf(stderr, "usage: %s <libtflite_jni.so> <backbone.tflite> <head.tflite> <fp32|fp16acc32> <images.txt> <out_dir> <iterations>\n", argv[0]); return 1; }
  const char* prec = argv[4]; int iterations = atoi(argv[7]);
  long t_load = now_us();
  if (tpu_init(argv[1], argv[2], 1)) return 1;
  long tpu_load_us = now_us() - t_load;
  std::vector<std::vector<char>> images;
  FILE* lst = fopen(argv[5], "r"); char line[4096];
  while (lst && fgets(line, sizeof(line), lst)) {
    line[strcspn(line, "\r\n")] = 0; if (!*line) continue;
    images.emplace_back();
    if (!read_file(line, &images.back()) || images.back().size() != tpu_input_bytes()) { fprintf(stderr, "FATAL: bad image %s\n", line); return 1; }
  }
  int n_feat = tpu_num_outputs();
  std::vector<std::vector<char>> feat(n_feat); std::vector<void*> feat_ptr(n_feat);
  for (int k = 0; k < n_feat; k++) { feat[k].resize(tpu_output_bytes(k)); feat_ptr[k] = feat[k].data(); }

  LiteRtEnvironment env; CHECK("Environment", LiteRtCreateEnvironment(0, NULL, &env));
  LiteRtModel model; CHECK("Model", LiteRtCreateModelFromFile(env, argv[3], &model));
  LiteRtOptions options; CHECK("Options", LiteRtCreateOptions(&options));
  CHECK("Accelerators", LiteRtSetOptionsHardwareAccelerators(options, kLiteRtHwAcceleratorGpu));
  LrtGpuOptions* g; CHECK("GpuOptions", LrtCreateGpuOptions(&g));
  CHECK("Precision", LrtSetGpuAcceleratorCompilationOptionsPrecision(
      g, strcmp(prec, "fp16acc32") == 0 ? kLiteRtDelegatePrecisionFp16WithFp32Accum : kLiteRtDelegatePrecisionFp32));
  const char* id; void* payload; void (*deleter)(void*);
  CHECK("OpaqueData", LrtGetOpaqueGpuOptionsData(g, &id, &payload, &deleter));
  LiteRtOpaqueOptions opaque; CHECK("Opaque", LiteRtCreateOpaqueOptions(id, payload, deleter, &opaque));
  CHECK("AddOpaque", LiteRtAddOpaqueOptions(options, opaque)); LrtDestroyGpuOptions(g);
  long c0 = now_us(); LiteRtCompiledModel compiled; CHECK("Compile", LiteRtCreateCompiledModel(env, model, options, &compiled));
  long gpu_compile_us = now_us() - c0;
  LiteRtSignature sig; CHECK("Signature", LiteRtGetModelSignature(model, 0, &sig));
  LiteRtParamIndex n_in = 0, n_out = 0;
  CHECK("NumIn", LiteRtGetNumSignatureInputs(sig, &n_in)); CHECK("NumOut", LiteRtGetNumSignatureOutputs(sig, &n_out));
  std::vector<LiteRtTensorBuffer> in_bufs(n_in), out_bufs(n_out); std::vector<size_t> in_sizes(n_in), out_sizes(n_out);
  std::vector<int> in_from(n_in, -1);
  for (int side = 0; side < 2; side++) {
    for (LiteRtParamIndex i = 0; i < (side ? n_out : n_in); i++) {
      LiteRtTensor t; LiteRtRankedTensorType type;
      if (side) CHECK("OutT", LiteRtGetSignatureOutputTensorByIndex(sig, i, &t)); else CHECK("InT", LiteRtGetSignatureInputTensorByIndex(sig, i, &t));
      CHECK("Type", LiteRtGetRankedTensorType(t, &type));
      size_t size = 4; for (unsigned d = 0; d < type.layout.rank; d++) size *= type.layout.dimensions[d];
      LiteRtTensorBufferRequirements r;
      if (side) CHECK("OutReq", LiteRtGetCompiledModelOutputBufferRequirements(compiled, 0, i, &r)); else CHECK("InReq", LiteRtGetCompiledModelInputBufferRequirements(compiled, 0, i, &r));
      CHECK("Buffer", LiteRtCreateManagedTensorBufferFromRequirements(env, &type, r, side ? &out_bufs[i] : &in_bufs[i]));
      (side ? out_sizes : in_sizes)[i] = size;
      if (!side) for (int k = 0; k < n_feat; k++) if (feat[k].size() == size) in_from[i] = k;
      if (!side && in_from[i] < 0) { fprintf(stderr, "FATAL: no TPU output matches head input %u (%zu bytes)\n", (unsigned)i, size); return 1; }
    }
  }
  printf("tpu_load_us=%ld (incl. TPU compile) gpu_compile_us=%ld images=%zu head_precision=%s\n", tpu_load_us, gpu_compile_us, images.size(), prec);
  std::vector<std::vector<char>> outh(n_out); for (size_t k = 0; k < n_out; k++) outh[k].resize(out_sizes[k]);
  std::vector<long> t_tpu, t_gpu, t_tot;
  for (int it = 0; it < iterations; it++) {
    size_t s = it % images.size();
    long a = now_us();
    if (tpu_run(images[s].data(), feat_ptr.data())) { fprintf(stderr, "FATAL: TPU run\n"); return 1; }
    long b = now_us();
    for (size_t i = 0; i < n_in; i++) {
      void* p; CHECK("LockIn", LiteRtLockTensorBuffer(in_bufs[i], &p, kLiteRtTensorBufferLockModeWrite));
      memcpy(p, feat[in_from[i]].data(), in_sizes[i]); CHECK("UnlockIn", LiteRtUnlockTensorBuffer(in_bufs[i]));
    }
    CHECK("Run", LiteRtRunCompiledModel(compiled, 0, n_in, in_bufs.data(), n_out, out_bufs.data()));
    for (size_t k = 0; k < n_out; k++) {
      void* p; CHECK("LockOut", LiteRtLockTensorBuffer(out_bufs[k], &p, kLiteRtTensorBufferLockModeRead));
      memcpy(outh[k].data(), p, out_sizes[k]); CHECK("UnlockOut", LiteRtUnlockTensorBuffer(out_bufs[k]));
    }
    long c = now_us();
    if (it < (int)images.size()) {
      for (size_t k = 0; k < n_out; k++) {
        char path[1024]; snprintf(path, sizeof(path), "%s/%zu_o%zu.bin", argv[6], s, k);
        FILE* f = fopen(path, "wb"); if (f) { fwrite(outh[k].data(), 1, out_sizes[k], f); fclose(f); }
      }
    } else { t_tpu.push_back(b - a); t_gpu.push_back(c - b); t_tot.push_back(c - a); }
  }
  printf("iters=%zu  total median=%ld us | TPU stage (image in, backbone, features out) median=%ld | GPU stage (features in, head, synchronized outputs) median=%ld\n",
         t_tot.size(), median(t_tot), median(t_tpu), median(t_gpu));
  return 0;
}
