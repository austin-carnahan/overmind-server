// Classic TFLite GPU delegate (OpenCL) correctness spike -- Segmentation and
// Labeling Lane, Step 2A (the GPU fallback path after ORT WebGPU's MatMul/Conv
// kernels crashed the Mali GPU).
//
// Runs one float .tflite model on CPU (the reference), then through
// TfLiteGpuDelegateV2 at full fp32 precision and with fp16 precision loss
// allowed, and compares every output element-wise -- the same discipline that
// caught LiteRT CompiledModel's all-zero GPU readback. Inputs are filled with
// a deterministic pattern; any float model works.
//
// usage: tflite-gpu-spike <model.tflite> [runs]
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <algorithm>
#include <vector>

#include "tensorflow/lite/c/c_api.h"
#include "tensorflow/lite/delegates/gpu/delegate.h"

static long now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

struct Result {
  bool ok = false;
  std::vector<std::vector<float>> outputs;
  long first_us = 0, median_us = 0, load_us = 0;
  int delegated_ok = 0;
};

static Result run(TfLiteModel* model, int mode, int runs) {
  // mode 0 = CPU, 1 = GPU fp32, 2 = GPU fp16 allowed
  Result r;
  long t0 = now_us();
  TfLiteInterpreterOptions* options = TfLiteInterpreterOptionsCreate();
  TfLiteInterpreterOptionsSetNumThreads(options, 4);
  TfLiteDelegate* delegate = NULL;
  if (mode > 0) {
    TfLiteGpuDelegateOptionsV2 gpu = TfLiteGpuDelegateOptionsV2Default();
    gpu.is_precision_loss_allowed = (mode == 2) ? 1 : 0;
    gpu.inference_preference = TFLITE_GPU_INFERENCE_PREFERENCE_SUSTAINED_SPEED;
    if (mode == 1) {
      gpu.inference_priority1 = TFLITE_GPU_INFERENCE_PRIORITY_MAX_PRECISION;
      gpu.inference_priority2 = TFLITE_GPU_INFERENCE_PRIORITY_MIN_LATENCY;
      gpu.inference_priority3 = TFLITE_GPU_INFERENCE_PRIORITY_MIN_MEMORY_USAGE;
    }
    delegate = TfLiteGpuDelegateV2Create(&gpu);
    if (!delegate) { printf("  GPU delegate creation failed\n"); return r; }
    TfLiteInterpreterOptionsAddDelegate(options, delegate);
  }
  TfLiteInterpreter* interp = TfLiteInterpreterCreate(model, options);
  if (!interp) { printf("  interpreter creation failed (delegate rejected the graph?)\n"); return r; }
  if (TfLiteInterpreterAllocateTensors(interp) != kTfLiteOk) { printf("  AllocateTensors failed\n"); return r; }
  r.load_us = now_us() - t0;

  int n_in = TfLiteInterpreterGetInputTensorCount(interp);
  for (int i = 0; i < n_in; i++) {
    TfLiteTensor* t = TfLiteInterpreterGetInputTensor(interp, i);
    if (TfLiteTensorType(t) != kTfLiteFloat32) { printf("  input %d is not float32\n", i); return r; }
    size_t n = TfLiteTensorByteSize(t) / 4;
    std::vector<float> buf(n);
    for (size_t k = 0; k < n; k++) buf[k] = (float)((k * 7 + i * 13) % 256) / 127.5f - 1.0f;
    TfLiteTensorCopyFromBuffer(t, buf.data(), n * 4);
  }

  std::vector<long> times;
  for (int k = 0; k < runs; k++) {
    long s = now_us();
    if (TfLiteInterpreterInvoke(interp) != kTfLiteOk) { printf("  Invoke failed\n"); return r; }
    times.push_back(now_us() - s);
  }
  r.first_us = times[0];
  std::vector<long> sorted(times.begin() + (runs > 1 ? 1 : 0), times.end());
  std::sort(sorted.begin(), sorted.end());
  r.median_us = sorted[sorted.size() / 2];

  int n_out = TfLiteInterpreterGetOutputTensorCount(interp);
  for (int i = 0; i < n_out; i++) {
    const TfLiteTensor* t = TfLiteInterpreterGetOutputTensor(interp, i);
    size_t n = TfLiteTensorByteSize(t) / 4;
    std::vector<float> buf(n);
    TfLiteTensorCopyToBuffer(t, buf.data(), n * 4);
    r.outputs.push_back(buf);
  }
  r.ok = true;
  TfLiteInterpreterDelete(interp);
  TfLiteInterpreterOptionsDelete(options);
  if (delegate) TfLiteGpuDelegateV2Delete(delegate);
  return r;
}

static void compare(const char* label, const Result& ref, const Result& got) {
  for (size_t i = 0; i < ref.outputs.size() && i < got.outputs.size(); i++) {
    const std::vector<float>& a = got.outputs[i];
    const std::vector<float>& b = ref.outputs[i];
    double dot = 0, na = 0, nb = 0, maxd = 0, sumd = 0;
    size_t argmax_a = 0, argmax_b = 0;
    bool all_zero = true;
    for (size_t k = 0; k < a.size(); k++) {
      double d = fabs((double)a[k] - b[k]);
      if (d > maxd) maxd = d;
      sumd += d;
      dot += (double)a[k] * b[k]; na += (double)a[k] * a[k]; nb += (double)b[k] * b[k];
      if (a[k] != 0) all_zero = false;
      if (a[k] > a[argmax_a]) argmax_a = k;
      if (b[k] > b[argmax_b]) argmax_b = k;
    }
    double cosine = (na > 0 && nb > 0) ? dot / sqrt(na * nb) : NAN;
    printf("  %s output %zu: cosine=%.6f max_abs_diff=%.6g mean_abs_diff=%.6g argmax=%zu (cpu %zu) all_zero=%d\n",
           label, i, cosine, maxd, sumd / a.size(), argmax_a, argmax_b, all_zero);
  }
}

int main(int argc, char** argv) {
  if (argc < 2) { fprintf(stderr, "usage: %s <model.tflite> [runs]\n", argv[0]); return 1; }
  int runs = argc > 2 ? atoi(argv[2]) : 10;
  TfLiteModel* model = TfLiteModelCreateFromFile(argv[1]);
  if (!model) { fprintf(stderr, "FATAL: cannot load %s\n", argv[1]); return 1; }
  const char* names[] = {"CPU", "GPU fp32", "GPU fp16"};
  Result cpu = run(model, 0, runs);
  printf("CPU      load_us=%ld first_us=%ld median_us=%ld\n", cpu.load_us, cpu.first_us, cpu.median_us);
  fflush(stdout);
  if (!cpu.ok) return 1;
  for (int mode = 1; mode <= 2; mode++) {
    Result g = run(model, mode, runs);
    if (!g.ok) { printf("%s FAILED\n", names[mode]); fflush(stdout); continue; }
    printf("%s load_us=%ld first_us=%ld median_us=%ld\n", names[mode], g.load_us, g.first_us, g.median_us);
    compare(names[mode], cpu, g);
    fflush(stdout);
  }
  TfLiteModelDelete(model);
  return 0;
}
