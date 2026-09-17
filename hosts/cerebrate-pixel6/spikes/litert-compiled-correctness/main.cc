#include <cstdint>
#include <cstdio>
#include <ctime>
#include <string>
#include <vector>

#include "litert/cc/litert_compiled_model.h"
#include "litert/cc/litert_environment.h"
#include "litert/cc/litert_tensor_buffer.h"

using namespace litert;

// Known reference for the deterministic i % 256 input pattern, established
// independently by cerebrate-infer (NNAPI), the plain-C LiteRT canary, and
// this benchmark's own CPU/XNNPACK path -- all agree on class 795.
static const int kReferenceClass = 795;

static long now_us() {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

static const char* AccelName(HwAccelerators a) {
  if (a == HwAccelerators::kCpu) return "CPU";
  if (a == HwAccelerators::kGpu) return "GPU";
  return "?";
}

static uint64_t Checksum(const std::vector<uint8_t>& v) {
  uint64_t sum = 0;
  for (uint8_t b : v) sum += b;
  return sum;
}

// Fills `out_vec` with the full output tensor and returns the argmax class,
// or -1 on read failure. `out_vec` is left empty on failure.
static int RunBench(Environment& env, const std::string& model_path,
                     HwAccelerators accel, int iters,
                     std::vector<uint8_t>* out_vec) {
  auto compiled = CompiledModel::Create(env, model_path, accel);
  if (!compiled.HasValue()) {
    fprintf(stderr, "[%s] Create failed: %s\n", AccelName(accel),
            compiled.Error().Message().c_str());
    return 1;
  }
  auto model = std::move(compiled.Value());

  auto inputs = model.CreateInputBuffers();
  auto outputs = model.CreateOutputBuffers();
  if (!inputs.HasValue() || !outputs.HasValue()) {
    fprintf(stderr, "[%s] buffer creation failed\n", AccelName(accel));
    return 1;
  }

  std::vector<uint8_t> dummy(224 * 224 * 3);
  for (size_t i = 0; i < dummy.size(); i++) dummy[i] = (uint8_t)(i % 256);
  auto write_status =
      inputs.Value()[0].Write<uint8_t>(absl::Span<const uint8_t>(dummy));
  if (!write_status.HasValue()) {
    fprintf(stderr, "[%s] write failed\n", AccelName(accel));
    return 1;
  }

  // warmup
  for (int i = 0; i < 3; i++) {
    model.Run(inputs.Value(), outputs.Value());
  }

  long total = 0, minv = -1, maxv = 0;
  for (int i = 0; i < iters; i++) {
    long t0 = now_us();
    auto status = model.Run(inputs.Value(), outputs.Value());
    long t1 = now_us();
    if (!status.HasValue()) {
      fprintf(stderr, "[%s] Run failed at iter %d: %s\n", AccelName(accel), i,
              status.Error().Message().c_str());
      return 1;
    }
    long d = t1 - t0;
    total += d;
    if (minv < 0 || d < minv) minv = d;
    if (d > maxv) maxv = d;
  }

  // Correctness check -- NOT present in the original benchmark. Read back
  // the FULL output vector (not just the argmax) so it can be compared
  // element-wise against another backend's run, not just spot-checked.
  out_vec->assign(1001, 0);
  auto out_read = outputs.Value()[0].Read<uint8_t>(
      absl::Span<uint8_t>(out_vec->data(), out_vec->size()));
  if (!out_read.HasValue()) {
    fprintf(stderr, "[%s] output read failed: %s\n", AccelName(accel),
            out_read.Error().Message().c_str());
    out_vec->clear();
    return 1;
  }

  int top_idx = -1;
  int top_val = -1;
  for (size_t i = 0; i < out_vec->size(); i++) {
    if ((int)(*out_vec)[i] > top_val) {
      top_val = (int)(*out_vec)[i];
      top_idx = (int)i;
    }
  }

  const char* verdict = (top_idx == kReferenceClass) ? "PASS" : "FAIL";
  printf("[%s] iters=%d mean_us=%.1f min_us=%ld max_us=%ld top_class=%d "
         "top_score=%d checksum=%llu reference_check=%s\n",
         AccelName(accel), iters, (double)total / iters, minv, maxv, top_idx,
         top_val, (unsigned long long)Checksum(*out_vec), verdict);
  return 0;
}

int main(int argc, char** argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: %s <model.tflite>\n", argv[0]);
    return 1;
  }
  std::string model_path = argv[1];

  auto env = Environment::Create(
      EnvironmentOptions(Span<const EnvironmentOptions::Option>()));
  if (!env.HasValue()) {
    fprintf(stderr, "Environment::Create failed: %s\n",
            env.Error().Message().c_str());
    return 1;
  }

  int rc = 0;
  std::vector<uint8_t> cpu_out, gpu_out;
  rc |= RunBench(env.Value(), model_path, HwAccelerators::kCpu, 30, &cpu_out);
  rc |= RunBench(env.Value(), model_path, HwAccelerators::kGpu, 30, &gpu_out);

  // Full-vector comparison, CPU (trusted reference) vs. GPU, with tolerance
  // for legitimate quantization/rounding differences between backends --
  // NNAPI and CPU/XNNPACK already disagree on exact quantized scores
  // (102 vs 120) while agreeing on class, so exact byte equality isn't the
  // right bar. +/-5 on the uint8 scale is generous enough to absorb that
  // kind of difference while still catching "GPU returned all zeros."
  if (!cpu_out.empty() && !gpu_out.empty() && cpu_out.size() == gpu_out.size()) {
    const int kTolerance = 5;
    size_t exact = 0, within_tolerance = 0;
    int max_abs_diff = 0;
    bool gpu_all_zero = true;
    for (size_t i = 0; i < cpu_out.size(); i++) {
      int diff = (int)cpu_out[i] - (int)gpu_out[i];
      if (diff == 0) exact++;
      if (diff < 0) diff = -diff;
      if (diff <= kTolerance) within_tolerance++;
      if (diff > max_abs_diff) max_abs_diff = diff;
      if (gpu_out[i] != 0) gpu_all_zero = false;
    }
    printf(
        "[COMPARE] cpu_vs_gpu: exact_matches=%zu/%zu within_tolerance(+-%d)="
        "%zu/%zu max_abs_diff=%d gpu_output_all_zero=%s\n",
        exact, cpu_out.size(), kTolerance, within_tolerance, cpu_out.size(),
        max_abs_diff, gpu_all_zero ? "true" : "false");
  } else {
    printf("[COMPARE] skipped -- one or both output reads failed\n");
  }

  return rc;
}
