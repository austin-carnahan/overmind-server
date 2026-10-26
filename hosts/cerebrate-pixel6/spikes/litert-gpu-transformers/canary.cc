// LiteRT CompiledModel C-API canary with buffer diagnostics (Segmentation and
// Labeling Lane, Step 2A: LiteRT 2.3.0 correctness regression).
//
// The C++ harness (litert-compiled-correctness) reproduced an all-zero GPU
// output on 2.3.0, with "Failed to get buffer requirements" for the input and
// output tensors. An all-zero host buffer alone doesn't say where the failure
// is (GPU execution, output binding, synchronization, or readback), so this
// canary separates them, through the plain C API only:
//   * records whether the compiled model reports buffer requirements for its
//     first input and output, and which buffer types it offers;
//   * runs with buffers created from those requirements, with plain
//     (padded, aligned) host memory, and with runtime-managed OpenCL buffers;
//   * pre-fills the output with a sentinel byte (0xAB) before running, waits
//     on any buffer event after, then counts sentinel bytes. Sentinel still
//     present = nothing ever wrote the bound output buffer; zeros = something
//     wrote zeros.
// Works for uint8 or float32 single-input/single-output models (deterministic
// input pattern); every GPU result is compared element-wise against the CPU
// run with requirement-based buffers.
//
// usage: litert-c-canary <model.tflite> [gpu|gpu+cpu] [default|fp16|fp32|fp16acc32]
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <vector>

#include "litert/c/litert_common.h"
#include "litert/c/litert_compiled_model.h"
#include "litert/c/litert_environment.h"
#include "litert/c/litert_event.h"
#include "litert/c/litert_model.h"
#include "litert/c/litert_opaque_options.h"
#include "litert/c/litert_options.h"
#include "litert/c/litert_tensor_buffer.h"
#include "litert/c/litert_tensor_buffer_requirements.h"
#include "litert/c/options/litert_gpu_options.h"

static const unsigned char kSentinel = 0xAB;

// GPU precision for the GPU cases (argv[3]): default | fp16 | fp32 | fp16acc32.
static LiteRtDelegatePrecision g_gpu_precision = kLiteRtDelegatePrecisionDefault;

static long now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

#define TRY(label, expr)                                              \
  do {                                                                \
    LiteRtStatus s_ = (expr);                                         \
    if (s_ != kLiteRtStatusOk) {                                      \
      printf("  %s: FAILED (status %d)\n", label, (int)s_);           \
      return false;                                                   \
    }                                                                 \
  } while (0)

struct Outcome {
  bool ok = false;
  bool is_float = false;
  std::vector<unsigned char> output;  // raw bytes
};

static size_t element_count(const LiteRtRankedTensorType& t) {
  size_t n = 1;
  for (unsigned i = 0; i < t.layout.rank; i++) n *= (size_t)t.layout.dimensions[i];
  return n;
}

static size_t element_size(LiteRtElementType e) {
  return e == kLiteRtElementTypeFloat32 ? 4 : 1;
}

static void describe_requirements(const char* what, LiteRtStatus status,
                                  LiteRtTensorBufferRequirements req) {
  if (status != kLiteRtStatusOk) {
    printf("  %s requirements: unavailable (status %d)\n", what, (int)status);
    return;
  }
  int n = 0;
  size_t size = 0;
  LiteRtGetNumTensorBufferRequirementsSupportedBufferTypes(req, &n);
  LiteRtGetTensorBufferRequirementsBufferSize(req, &size);
  printf("  %s requirements: size=%zu types=[", what, size);
  for (int i = 0; i < n; i++) {
    LiteRtTensorBufferType t;
    LiteRtGetTensorBufferRequirementsSupportedTensorBufferType(req, i, &t);
    printf("%s%d", i ? "," : "", (int)t);
  }
  printf("]\n");
}

enum Strategy { kFromRequirements, kHostMemory, kOpenClBuffer };
static const char* kStrategyNames[] = {"requirement-based", "host-memory (aligned, padded)",
                                       "managed OpenCL"};

// One accelerator + one buffer strategy.
static bool run_case(LiteRtEnvironment env, LiteRtModel model,
                     LiteRtHwAcceleratorSet accel, Strategy strategy,
                     Outcome* out) {
  const char* name = accel == kLiteRtHwAcceleratorCpu ? "CPU" : (accel == kLiteRtHwAcceleratorGpu ? "GPU" : "GPU+CPU");
  printf("[%s, %s buffers]\n", name, kStrategyNames[strategy]);

  LiteRtOptions options;
  TRY("CreateOptions", LiteRtCreateOptions(&options));
  TRY("SetOptionsHardwareAccelerators", LiteRtSetOptionsHardwareAccelerators(options, accel));
  if ((accel & kLiteRtHwAcceleratorGpu) && g_gpu_precision != kLiteRtDelegatePrecisionDefault) {
    LrtGpuOptions* gpu_opts;
    TRY("LrtCreateGpuOptions", LrtCreateGpuOptions(&gpu_opts));
    TRY("SetPrecision", LrtSetGpuAcceleratorCompilationOptionsPrecision(gpu_opts, g_gpu_precision));
    const char* id; void* payload; void (*deleter)(void*);
    TRY("LrtGetOpaqueGpuOptionsData", LrtGetOpaqueGpuOptionsData(gpu_opts, &id, &payload, &deleter));
    LiteRtOpaqueOptions opaque;
    TRY("CreateOpaqueOptions", LiteRtCreateOpaqueOptions(id, payload, deleter, &opaque));
    TRY("AddOpaqueOptions", LiteRtAddOpaqueOptions(options, opaque));
    LrtDestroyGpuOptions(gpu_opts);
    printf("  GPU precision option set to %d\n", (int)g_gpu_precision);
  }
  LiteRtCompiledModel compiled;
  long t0 = now_us();
  TRY("CreateCompiledModel", LiteRtCreateCompiledModel(env, model, options, &compiled));
  printf("  compiled in %ld us\n", now_us() - t0);

  LiteRtSignature sig;
  TRY("GetModelSignature", LiteRtGetModelSignature(model, 0, &sig));
  LiteRtTensor in_tensor, out_tensor;
  TRY("GetSignatureInputTensorByIndex", LiteRtGetSignatureInputTensorByIndex(sig, 0, &in_tensor));
  TRY("GetSignatureOutputTensorByIndex", LiteRtGetSignatureOutputTensorByIndex(sig, 0, &out_tensor));
  LiteRtRankedTensorType in_type, out_type;
  TRY("GetRankedTensorType(in)", LiteRtGetRankedTensorType(in_tensor, &in_type));
  TRY("GetRankedTensorType(out)", LiteRtGetRankedTensorType(out_tensor, &out_type));
  const size_t in_n = element_count(in_type), out_n = element_count(out_type);
  const size_t in_size = in_n * element_size(in_type.element_type);
  const size_t out_size = out_n * element_size(out_type.element_type);
  out->is_float = out_type.element_type == kLiteRtElementTypeFloat32;
  printf("  input element_type=%d bytes=%zu, output element_type=%d bytes=%zu\n",
         (int)in_type.element_type, in_size, (int)out_type.element_type, out_size);

  LiteRtTensorBufferRequirements in_req = NULL, out_req = NULL;
  LiteRtStatus in_rs = LiteRtGetCompiledModelInputBufferRequirements(compiled, 0, 0, &in_req);
  LiteRtStatus out_rs = LiteRtGetCompiledModelOutputBufferRequirements(compiled, 0, 0, &out_req);
  describe_requirements("input", in_rs, in_req);
  describe_requirements("output", out_rs, out_req);

  LiteRtTensorBuffer in_buf, out_buf;
  if (strategy == kFromRequirements) {
    if (in_rs != kLiteRtStatusOk || out_rs != kLiteRtStatusOk) {
      printf("  skipped: no requirements to create buffers from\n");
      return false;
    }
    TRY("CreateManagedTensorBufferFromRequirements(in)",
        LiteRtCreateManagedTensorBufferFromRequirements(env, &in_type, in_req, &in_buf));
    TRY("CreateManagedTensorBufferFromRequirements(out)",
        LiteRtCreateManagedTensorBufferFromRequirements(env, &out_type, out_req, &out_buf));
  } else if (strategy == kHostMemory) {
    // Padded: XNNPACK reads up to XNN_EXTRA_BYTES past the end of an input.
    void *in_host = NULL, *out_host = NULL;
    if (posix_memalign(&in_host, 64, in_size + 256) || posix_memalign(&out_host, 64, out_size + 256))
      return false;
    TRY("CreateTensorBufferFromHostMemory(in)",
        LiteRtCreateTensorBufferFromHostMemory(&in_type, in_host, in_size, NULL, &in_buf));
    TRY("CreateTensorBufferFromHostMemory(out)",
        LiteRtCreateTensorBufferFromHostMemory(&out_type, out_host, out_size, NULL, &out_buf));
  } else {
    TRY("CreateManagedTensorBuffer(in, OpenClBuffer)",
        LiteRtCreateManagedTensorBuffer(env, kLiteRtTensorBufferTypeOpenClBuffer, &in_type,
                                        in_size, &in_buf));
    TRY("CreateManagedTensorBuffer(out, OpenClBuffer)",
        LiteRtCreateManagedTensorBuffer(env, kLiteRtTensorBufferTypeOpenClBuffer, &out_type,
                                        out_size, &out_buf));
  }
  LiteRtTensorBufferType in_bt, out_bt;
  LiteRtGetTensorBufferType(in_buf, &in_bt);
  LiteRtGetTensorBufferType(out_buf, &out_bt);
  printf("  buffer types: input=%d output=%d\n", (int)in_bt, (int)out_bt);

  // Input: deterministic pattern; output: sentinel. Through Lock/Unlock so any
  // device-side copy is the runtime's job.
  void* p;
  TRY("Lock(in, write)", LiteRtLockTensorBuffer(in_buf, &p, kLiteRtTensorBufferLockModeWrite));
  for (size_t i = 0; i < in_n; i++) {
    if (in_type.element_type == kLiteRtElementTypeFloat32)
      ((float*)p)[i] = (float)(i % 256) / 127.5f - 1.0f;
    else
      ((unsigned char*)p)[i] = (unsigned char)(i % 256);
  }
  TRY("Unlock(in)", LiteRtUnlockTensorBuffer(in_buf));
  TRY("Lock(out, write)", LiteRtLockTensorBuffer(out_buf, &p, kLiteRtTensorBufferLockModeWrite));
  memset(p, kSentinel, out_size);
  TRY("Unlock(out)", LiteRtUnlockTensorBuffer(out_buf));

  const int iters = 30;
  long total = 0, minv = 1L << 40, maxv = 0;
  for (int k = 0; k < iters; k++) {
    long s = now_us();
    TRY("RunCompiledModel", LiteRtRunCompiledModel(compiled, 0, 1, &in_buf, 1, &out_buf));
    long d = now_us() - s;
    total += d;
    if (d < minv) minv = d;
    if (d > maxv) maxv = d;
  }

  bool has_event = false;
  LiteRtHasTensorBufferEvent(out_buf, &has_event);
  if (has_event) {
    LiteRtEvent ev;
    if (LiteRtGetTensorBufferEvent(out_buf, &ev) == kLiteRtStatusOk)
      printf("  output buffer had an event; wait status %d\n", (int)LiteRtWaitEvent(ev, 5000));
  } else {
    printf("  output buffer had no event\n");
  }

  TRY("Lock(out, read)", LiteRtLockTensorBuffer(out_buf, &p, kLiteRtTensorBufferLockModeRead));
  out->output.assign((unsigned char*)p, (unsigned char*)p + out_size);
  TRY("Unlock(out)", LiteRtUnlockTensorBuffer(out_buf));

  size_t sentinel = 0;
  for (size_t i = 0; i < out_size; i++)
    if (out->output[i] == kSentinel) sentinel++;
  size_t top = 0;
  for (size_t i = 0; i < out_n; i++) {
    double v = out->is_float ? ((float*)out->output.data())[i] : out->output[i];
    double best = out->is_float ? ((float*)out->output.data())[top] : out->output[top];
    if (v > best) top = i;
  }
  printf("  iters=%d mean_us=%.1f min_us=%ld max_us=%ld top_class=%zu sentinel_bytes=%zu/%zu\n",
         iters, (double)total / iters, minv, maxv, top, sentinel, out_size);
  fflush(stdout);

  LiteRtDestroyTensorBuffer(in_buf);
  LiteRtDestroyTensorBuffer(out_buf);
  LiteRtDestroyCompiledModel(compiled);
  LiteRtDestroyOptions(options);
  out->ok = true;
  return true;
}

static void compare(const char* label, const Outcome& ref, const Outcome& got) {
  if (!ref.ok || !got.ok) return;
  size_t n = ref.is_float ? ref.output.size() / 4 : ref.output.size();
  double dot = 0, na = 0, nb = 0, maxd = 0;
  size_t exact = 0;
  for (size_t i = 0; i < n; i++) {
    double a = ref.is_float ? ((const float*)ref.output.data())[i] : ref.output[i];
    double b = got.is_float ? ((const float*)got.output.data())[i] : got.output[i];
    double d = fabs(a - b);
    if (d == 0) exact++;
    if (d > maxd) maxd = d;
    dot += a * b; na += a * a; nb += b * b;
  }
  printf("[COMPARE] %s vs CPU: cosine=%.6f max_abs_diff=%.6g exact=%zu/%zu\n", label,
         (na > 0 && nb > 0) ? dot / sqrt(na * nb) : NAN, maxd, exact, n);
}

int main(int argc, char** argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: %s <model.tflite>\n", argv[0]);
    return 1;
  }
  LiteRtEnvironment env;
  if (LiteRtCreateEnvironment(0, NULL, &env) != kLiteRtStatusOk) {
    fprintf(stderr, "FATAL: CreateEnvironment\n");
    return 1;
  }
  LiteRtModel model;
  if (LiteRtCreateModelFromFile(env, argv[1], &model) != kLiteRtStatusOk) {
    fprintf(stderr, "FATAL: CreateModelFromFile\n");
    return 1;
  }
  // argv[2] == "gpu+cpu": let the GPU cases fall back to CPU for nodes the GPU
  // accelerator rejects, instead of GPU only.
  LiteRtHwAcceleratorSet gpu = kLiteRtHwAcceleratorGpu;
  if (argc > 3) {
    if (strcmp(argv[3], "fp16") == 0) g_gpu_precision = kLiteRtDelegatePrecisionFp16;
    else if (strcmp(argv[3], "fp32") == 0) g_gpu_precision = kLiteRtDelegatePrecisionFp32;
    else if (strcmp(argv[3], "fp16acc32") == 0) g_gpu_precision = kLiteRtDelegatePrecisionFp16WithFp32Accum;
  }
  if (argc > 2 && strcmp(argv[2], "gpu+cpu") == 0) gpu = (LiteRtHwAcceleratorSet)(kLiteRtHwAcceleratorGpu | kLiteRtHwAcceleratorCpu);
  Outcome cpu_req, cpu_host, gpu_req, gpu_host, gpu_cl;
  run_case(env, model, kLiteRtHwAcceleratorCpu, kFromRequirements, &cpu_req);
  run_case(env, model, kLiteRtHwAcceleratorCpu, kHostMemory, &cpu_host);
  run_case(env, model, gpu, kFromRequirements, &gpu_req);
  run_case(env, model, gpu, kHostMemory, &gpu_host);
  run_case(env, model, gpu, kOpenClBuffer, &gpu_cl);
  compare("CPU host-memory", cpu_req, cpu_host);
  compare("GPU requirement-based", cpu_req, gpu_req);
  compare("GPU host-memory", cpu_req, gpu_host);
  compare("GPU managed OpenCL", cpu_req, gpu_cl);
  LiteRtDestroyModel(model);
  LiteRtDestroyEnvironment(env);
  return 0;
}
