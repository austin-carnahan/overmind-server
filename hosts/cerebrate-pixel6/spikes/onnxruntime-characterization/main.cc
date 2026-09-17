// ONNX Runtime characterization spike (Operational Model Catalog v4,
// Phase C Stage 1): CPU and XNNPACK correctness + timing on the exact
// same MobileNet v1 1.0 224 quantized canary used by every other backend
// in this project -- not a different model, so a class mismatch can only
// mean a real backend problem, not a confounded "different ground truth."
//
// The .tflite file already deployed on this device was converted to ONNX
// via tf2onnx (preserving the same quantized weights, not a re-export
// from a different source), then independently verified off-device with
// ONNX Runtime's Python bindings before this spike was even written: the
// same deterministic i%256 input produces the same top class (795) as
// every other backend. See README.md for the exact conversion command
// and that verification.
//
// Deliberately a one-shot standalone spike, not integrated into
// cerebrate-infer -- matches the litert-compiled-correctness spike's own
// posture (hosts/cerebrate-pixel6/spikes/litert-compiled-correctness/).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

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
static void run_and_check(const char* label, const OrtEnv* env,
                           const char* model_path, OrtSessionOptions* options,
                           const unsigned char* input_data) {
  // stderr progress markers, flushed per-step, are deliberate: this spike
  // crashes deep inside libonnxruntime.so on the XNNPACK path (see
  // README.md), and stdout's verdict line is otherwise lost on a crash
  // (fully buffered when not a tty) -- these are what actually let that
  // crash get localized to Run() rather than session/tensor setup.
  fprintf(stderr, "[%s] creating session...\n", label); fflush(stderr);
  long t_load0 = now_us();
  OrtSession* session = NULL;
  CHECK_STATUS(g_api->CreateSession(env, model_path, options, &session));
  long t_load1 = now_us();

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

  fprintf(stderr, "[%s] running...\n", label); fflush(stderr);
  long t_run0 = now_us();
  CHECK_STATUS(g_api->Run(session, NULL, input_names,
                           (const OrtValue* const*)&input_tensor, 1,
                           output_names, 1, &output_tensor));
  long t_run1 = now_us();

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
      "load_us=%ld run_us=%ld\n",
      label, top_idx, top_val, kReferenceClass, verdict, t_load1 - t_load0,
      t_run1 - t_run0);
  fflush(stdout);

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

  // Run 1: default CPU execution provider (nothing appended).
  {
    OrtSessionOptions* options = NULL;
    CHECK_STATUS(g_api->CreateSessionOptions(&options));
    run_and_check("CPU", env, model_path, options, input_data);
    g_api->ReleaseSessionOptions(options);
  }

  // Run 2: explicit XNNPACK execution provider.
  {
    OrtSessionOptions* options = NULL;
    CHECK_STATUS(g_api->CreateSessionOptions(&options));
    CHECK_STATUS(g_api->SessionOptionsAppendExecutionProvider(
        options, "XNNPACK", NULL, NULL, 0));
    run_and_check("XNNPACK", env, model_path, options, input_data);
    g_api->ReleaseSessionOptions(options);
  }

  free(input_data);
  g_api->ReleaseEnv(env);
  return 0;
}
