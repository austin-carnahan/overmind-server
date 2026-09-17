// ONNX Runtime characterization spike (Operational Model Catalog v4,
// Phase C): CPU/XNNPACK (Stage 1) and NNAPI (Stage 2) correctness +
// timing on the exact same MobileNet v1 1.0 224 quantized canary used by
// every other backend in this project -- not a different model, so a
// class mismatch can only mean a real backend problem, not a confounded
// "different ground truth."
//
// The .tflite file already deployed on this device was converted to ONNX
// via tf2onnx (preserving the same quantized weights, not a re-export
// from a different source), then independently verified off-device with
// ONNX Runtime's Python bindings before this spike was even written: the
// same deterministic i%256 input produces the same top class (795) as
// every other backend. See README.md for the exact conversion command
// and that verification.
//
// Stage 2 (NNAPI) runs with a stored CPU reference output for a full
// element-wise comparison, not just argmax -- the same discipline that
// caught LiteRT CompiledModel's GPU readback bug (a delegate can "run
// successfully" and still return garbage or an all-zero buffer). A
// CreateSession/Run failure under NNAPI_FLAG_CPU_DISABLED is treated as
// a real, informative result (not a program crash) and reported clearly,
// since ORT returning an error status when it genuinely can't avoid CPU
// fallback for some operator is exactly the kind of honest failure this
// characterization is looking for.
//
// Deliberately a one-shot standalone spike, not integrated into
// cerebrate-infer -- matches the litert-compiled-correctness spike's own
// posture (hosts/cerebrate-pixel6/spikes/litert-compiled-correctness/).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "nnapi_provider_factory.h"
#include "onnxruntime_c_api.h"

static const OrtApi* g_api = NULL;

static long now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

// Known reference for the deterministic i % 256 input pattern, established
// with the real quantized MobileNet v1 1.0 224 model -- NNAPI/google-edgetpu,
// LiteRT CompiledModel CPU, and this benchmark's own CPU/XNNPACK path all
// agree on class 795 (see litert-compiled-correctness/main.cc).
static const int kReferenceClass = 795;
static const int kInputSize = 224 * 224 * 3;

#define CHECK_STATUS(expr)                                               \
  do {                                                                   \
    OrtStatus* status = (expr);                                          \
    if (status != NULL) {                                                \
      fprintf(stderr, "FATAL: %s -> %s\n", #expr,                        \
              g_api->GetErrorMessage(status));                           \
      g_api->ReleaseStatus(status);                                      \
      exit(1);                                                           \
    }                                                                    \
  } while (0)

// Runs the model once under the given session options (already configured
// with whichever execution provider(s) the caller wants) and reports
// correctness + timing. Does not take ownership of `options`.
//
// CreateSession/Run failures are reported as a clean [ERROR] line, not a
// program abort -- a real, informative outcome for e.g. NNAPI_FLAG_CPU_DISABLED
// forcing an honest failure when some operator can't avoid CPU fallback.
// Setup calls that "should never fail regardless of EP" (memory info,
// tensor creation) still use the fatal CHECK_STATUS.
//
// If `reference_output` is non-NULL, does a full 1001-element comparison
// against it (exact matches, matches within a small tolerance, max
// absolute difference) in addition to the argmax check -- the same
// discipline that caught LiteRT CompiledModel's GPU readback bug, so an
// EP that "runs successfully" but returns garbage or all-zero data
// doesn't get mistaken for a pass. If `capture_output` is non-NULL and
// the run succeeds, copies this run's output into it (1001 bytes) so a
// later run can be compared against it.
static const int kToleranceForMatch = 5;

static void run_and_check(const char* label, const OrtEnv* env,
                           const char* model_path, OrtSessionOptions* options,
                           const unsigned char* input_data,
                           const unsigned char* reference_output,
                           unsigned char* capture_output) {
  long t_load0 = now_us();
  OrtSession* session = NULL;
  OrtStatus* status = g_api->CreateSession(env, model_path, options, &session);
  long t_load1 = now_us();
  if (status != NULL) {
    printf("%-10s [ERROR] CreateSession: %s\n", label, g_api->GetErrorMessage(status));
    fflush(stdout);
    g_api->ReleaseStatus(status);
    return;
  }

  OrtMemoryInfo* mem_info = NULL;
  CHECK_STATUS(g_api->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &mem_info));

  int64_t input_shape[4] = {1, 224, 224, 3};
  OrtValue* input_tensor = NULL;
  CHECK_STATUS(g_api->CreateTensorWithDataAsOrtValue(
      mem_info, (void*)input_data, (size_t)kInputSize, input_shape, 4,
      ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8, &input_tensor));

  const char* input_names[] = {"input"};
  const char* output_names[] = {"MobilenetV1/Predictions/Reshape_1"};
  OrtValue* output_tensor = NULL;

  long t_run0 = now_us();
  status = g_api->Run(session, NULL, input_names,
                       (const OrtValue* const*)&input_tensor, 1,
                       output_names, 1, &output_tensor);
  long t_run1 = now_us();
  if (status != NULL) {
    printf("%-10s [ERROR] Run: %s\n", label, g_api->GetErrorMessage(status));
    fflush(stdout);
    g_api->ReleaseStatus(status);
    g_api->ReleaseValue(input_tensor);
    g_api->ReleaseMemoryInfo(mem_info);
    g_api->ReleaseSession(session);
    return;
  }

  unsigned char* output_data = NULL;
  CHECK_STATUS(g_api->GetTensorMutableData(output_tensor, (void**)&output_data));

  // Output is [1, 1001] uint8 (quantized softmax-ish scores); argmax is
  // the predicted class, same convention already used elsewhere in this
  // project for this exact model.
  int top_idx = 0;
  unsigned char top_val = 0;
  for (int i = 0; i < 1001; i++) {
    if (output_data[i] > top_val) {
      top_val = output_data[i];
      top_idx = i;
    }
  }
  const char* verdict = (top_idx == kReferenceClass) ? "PASS" : "FAIL";

  printf(
      "%-10s top_class=%d top_val=%u expected=%d [%s] "
      "load_us=%ld run_us=%ld",
      label, top_idx, top_val, kReferenceClass, verdict, t_load1 - t_load0,
      t_run1 - t_run0);

  if (reference_output != NULL) {
    int exact_matches = 0, within_tolerance = 0, max_abs_diff = 0;
    for (int i = 0; i < 1001; i++) {
      int diff = output_data[i] - reference_output[i];
      if (diff < 0) diff = -diff;
      if (diff == 0) exact_matches++;
      if (diff <= kToleranceForMatch) within_tolerance++;
      if (diff > max_abs_diff) max_abs_diff = diff;
    }
    printf(" exact_matches=%d/1001 within_tolerance(+-%d)=%d/1001 max_abs_diff=%d",
           exact_matches, kToleranceForMatch, within_tolerance, max_abs_diff);
  }
  printf("\n");
  fflush(stdout);

  if (capture_output != NULL) {
    memcpy(capture_output, output_data, 1001);
  }

  g_api->ReleaseValue(output_tensor);
  g_api->ReleaseValue(input_tensor);
  g_api->ReleaseMemoryInfo(mem_info);
  g_api->ReleaseSession(session);
}

int main(int argc, char** argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: %s <mobilenet_v1_1.0_224_quant.onnx>\n", argv[0]);
    return 1;
  }
  const char* model_path = argv[1];

  const OrtApiBase* api_base = OrtGetApiBase();
  g_api = api_base->GetApi(ORT_API_VERSION);
  if (!g_api) {
    fprintf(stderr, "FATAL: OrtGetApiBase()->GetApi() returned NULL\n");
    return 1;
  }

  OrtEnv* env = NULL;
  CHECK_STATUS(g_api->CreateEnv(ORT_LOGGING_LEVEL_WARNING, "onnxruntime-characterization", &env));

  unsigned char* input_data = (unsigned char*)malloc(kInputSize);
  for (int i = 0; i < kInputSize; i++) input_data[i] = (unsigned char)(i % 256);

  unsigned char cpu_reference_output[1001];

  // Run 1: default CPU execution provider (nothing appended). This run's
  // output becomes the reference vector every later run is compared
  // against, not just its own argmax.
  {
    OrtSessionOptions* options = NULL;
    CHECK_STATUS(g_api->CreateSessionOptions(&options));
    run_and_check("CPU", env, model_path, options, input_data, NULL, cpu_reference_output);
    g_api->ReleaseSessionOptions(options);
  }

  // Run 2 (Stage 2): NNAPI with NNAPI_FLAG_CPU_DISABLED -- per catalog v4
  // Section 6.2's acceptance criteria, CPU fallback through NNAPI must be
  // disabled so an "accelerated" result can't simply be NNAPI's own
  // nnapi-reference CPU execution. If this fails, that's the honest
  // Stage 2 answer for this model, not a bug in this spike.
  {
    OrtSessionOptions* options = NULL;
    CHECK_STATUS(g_api->CreateSessionOptions(&options));
    CHECK_STATUS(OrtSessionOptionsAppendExecutionProvider_Nnapi(options, NNAPI_FLAG_CPU_DISABLED));
    run_and_check("NNAPI(no-cpu)", env, model_path, options, input_data, cpu_reference_output, NULL);
    g_api->ReleaseSessionOptions(options);
  }

  // Run 3: NNAPI with CPU fallback allowed (the default/permissive
  // configuration) -- a comparison point to isolate whether
  // NNAPI_FLAG_CPU_DISABLED specifically is what fails, versus NNAPI
  // integration failing outright regardless of the flag.
  {
    OrtSessionOptions* options = NULL;
    CHECK_STATUS(g_api->CreateSessionOptions(&options));
    CHECK_STATUS(OrtSessionOptionsAppendExecutionProvider_Nnapi(options, NNAPI_FLAG_USE_NONE));
    run_and_check("NNAPI(cpu-ok)", env, model_path, options, input_data, cpu_reference_output, NULL);
    g_api->ReleaseSessionOptions(options);
  }

  // Run 4 (Stage 1, deliberately last): explicit XNNPACK execution
  // provider. Runs after the NNAPI runs, not before, because it crashes
  // the whole process (see README.md's Stage 1 findings) -- ordering it
  // last means that known crash doesn't prevent the NNAPI runs (Stage 2's
  // actual subject) from ever executing.
  {
    OrtSessionOptions* options = NULL;
    CHECK_STATUS(g_api->CreateSessionOptions(&options));
    CHECK_STATUS(g_api->SessionOptionsAppendExecutionProvider(
        options, "XNNPACK", NULL, NULL, 0));
    run_and_check("XNNPACK", env, model_path, options, input_data, cpu_reference_output, NULL);
    g_api->ReleaseSessionOptions(options);
  }

  free(input_data);
  g_api->ReleaseEnv(env);
  return 0;
}
