// Granite-Docling vision encoder characterization spike (next high-value
// experiment after the Docling + Pixel llama.cpp experiment,
// experiments/docling/README.md): isolates the ~99%-of-runtime
// vision-encoding bottleneck measured there and asks whether ORT's NNAPI
// execution provider can accelerate it on this Pixel 6, the same way
// Phase C asked for MobileNet -- CPU first, then NNAPI with CPU fallback
// explicitly disabled, verified against real logcat delegation evidence,
// not just a passing Run().
//
// Correctness is judged on the intermediate image-feature tensor
// (image_features / HF's image_hidden_states), not generated DocTags
// text -- comparing full 13*64*576-element float32 tensors against a
// CPU-computed reference (exact_matches/within_tolerance/max_abs_diff/
// cosine similarity), the same discipline that caught LiteRT
// CompiledModel's GPU readback bug and ORT's own XNNPACK crash earlier
// in this project.
//
// Inputs are the *exact* pixel_values/pixel_attention_mask tensors
// dumped from the real HF processor (dump_vision_encoder_tensors.py) --
// deliberately not reimplementing Idefics3's image resize/tiling logic
// in C, the same reasoning the MobileNet canary used a fixed
// deterministic input pattern instead of a real image decoder.
#include <math.h>
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

// Parses "shapes.txt": lines of "<name> <dim0> <dim1> ...".
typedef struct {
  char name[64];
  int64_t dims[8];
  int ndims;
} TensorShape;

static int find_shape(TensorShape* shapes, int n, const char* name, TensorShape** out) {
  for (int i = 0; i < n; i++) {
    if (strcmp(shapes[i].name, name) == 0) {
      *out = &shapes[i];
      return 1;
    }
  }
  return 0;
}

static int load_shapes(const char* path, TensorShape* shapes, int max_shapes) {
  FILE* f = fopen(path, "r");
  if (!f) {
    fprintf(stderr, "FATAL: cannot open %s\n", path);
    exit(1);
  }
  char line[512];
  int n = 0;
  while (n < max_shapes && fgets(line, sizeof(line), f)) {
    TensorShape* s = &shapes[n];
    char* tok = strtok(line, " \t\n");
    if (!tok) continue;
    strncpy(s->name, tok, sizeof(s->name) - 1);
    s->ndims = 0;
    while ((tok = strtok(NULL, " \t\n")) != NULL && s->ndims < 8) {
      s->dims[s->ndims++] = atoll(tok);
    }
    n++;
  }
  fclose(f);
  return n;
}

static int64_t num_elements(const TensorShape* s) {
  int64_t n = 1;
  for (int i = 0; i < s->ndims; i++) n *= s->dims[i];
  return n;
}

static void* read_binary_file(const char* path, size_t expected_bytes) {
  FILE* f = fopen(path, "rb");
  if (!f) {
    fprintf(stderr, "FATAL: cannot open %s\n", path);
    exit(1);
  }
  void* buf = malloc(expected_bytes);
  size_t got = fread(buf, 1, expected_bytes, f);
  fclose(f);
  if (got != expected_bytes) {
    fprintf(stderr, "FATAL: %s: read %zu bytes, expected %zu\n", path, got, expected_bytes);
    exit(1);
  }
  return buf;
}

// Runs the vision encoder once under the given session options and
// compares its output against the CPU reference. Non-fatal on
// CreateSession/Run failure (a real, informative outcome for e.g.
// NNAPI_FLAG_CPU_DISABLED).
static void run_and_check(const char* label, const OrtEnv* env, const char* model_path,
                           OrtSessionOptions* options, const float* pixel_values,
                           const TensorShape* pv_shape, const unsigned char* pixel_mask,
                           const TensorShape* mask_shape, const float* reference_output,
                           int64_t ref_count) {
  long t_load0 = now_us();
  OrtSession* session = NULL;
  OrtStatus* status = g_api->CreateSession(env, model_path, options, &session);
  long t_load1 = now_us();
  if (status != NULL) {
    printf("%-14s [ERROR] CreateSession: %s\n", label, g_api->GetErrorMessage(status));
    g_api->ReleaseStatus(status);
    return;
  }

  OrtMemoryInfo* mem_info = NULL;
  CHECK_STATUS(g_api->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &mem_info));

  OrtValue* pv_tensor = NULL;
  CHECK_STATUS(g_api->CreateTensorWithDataAsOrtValue(
      mem_info, (void*)pixel_values, (size_t)num_elements(pv_shape) * sizeof(float),
      pv_shape->dims, pv_shape->ndims, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT, &pv_tensor));

  OrtValue* mask_tensor = NULL;
  CHECK_STATUS(g_api->CreateTensorWithDataAsOrtValue(
      mem_info, (void*)pixel_mask, (size_t)num_elements(mask_shape),
      mask_shape->dims, mask_shape->ndims, ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL, &mask_tensor));

  const char* input_names[] = {"pixel_values", "pixel_attention_mask"};
  const OrtValue* input_values[] = {pv_tensor, mask_tensor};
  const char* output_names[] = {"image_features"};
  OrtValue* output_tensor = NULL;

  long t_run0 = now_us();
  status = g_api->Run(session, NULL, input_names, input_values, 2, output_names, 1, &output_tensor);
  long t_run1 = now_us();
  if (status != NULL) {
    printf("%-14s [ERROR] Run: %s\n", label, g_api->GetErrorMessage(status));
    g_api->ReleaseStatus(status);
    g_api->ReleaseValue(pv_tensor);
    g_api->ReleaseValue(mask_tensor);
    g_api->ReleaseMemoryInfo(mem_info);
    g_api->ReleaseSession(session);
    return;
  }

  float* output_data = NULL;
  CHECK_STATUS(g_api->GetTensorMutableData(output_tensor, (void**)&output_data));

  int64_t exact_matches = 0, within_tolerance = 0;
  double max_abs_diff = 0.0, sum_abs_diff = 0.0;
  double dot = 0.0, norm_a = 0.0, norm_b = 0.0;
  const double kTolerance = 0.01;
  for (int64_t i = 0; i < ref_count; i++) {
    double a = (double)output_data[i];
    double b = (double)reference_output[i];
    double diff = fabs(a - b);
    if (diff == 0.0) exact_matches++;
    if (diff <= kTolerance) within_tolerance++;
    if (diff > max_abs_diff) max_abs_diff = diff;
    sum_abs_diff += diff;
    dot += a * b;
    norm_a += a * a;
    norm_b += b * b;
  }
  double cosine_sim = dot / (sqrt(norm_a) * sqrt(norm_b) + 1e-12);

  printf(
      "%-14s load_us=%-8ld run_us=%-8ld exact=%lld/%lld within_tol(+-%.2f)=%lld/%lld "
      "max_abs_diff=%.6f mean_abs_diff=%.6e cosine_sim=%.8f\n",
      label, t_load1 - t_load0, t_run1 - t_run0, (long long)exact_matches, (long long)ref_count,
      kTolerance, (long long)within_tolerance, (long long)ref_count, max_abs_diff,
      sum_abs_diff / (double)ref_count, cosine_sim);

  g_api->ReleaseValue(output_tensor);
  g_api->ReleaseValue(pv_tensor);
  g_api->ReleaseValue(mask_tensor);
  g_api->ReleaseMemoryInfo(mem_info);
  g_api->ReleaseSession(session);
}

int main(int argc, char** argv) {
  if (argc < 3) {
    fprintf(stderr, "usage: %s <vision_encoder.onnx> <tensors_dir>\n", argv[0]);
    return 1;
  }
  const char* model_path = argv[1];
  const char* tensors_dir = argv[2];

  char shapes_path[512], pv_path[512], mask_path[512], ref_path[512];
  snprintf(shapes_path, sizeof(shapes_path), "%s/shapes.txt", tensors_dir);
  snprintf(pv_path, sizeof(pv_path), "%s/pixel_values.f32.bin", tensors_dir);
  snprintf(mask_path, sizeof(mask_path), "%s/pixel_attention_mask.bool.bin", tensors_dir);
  snprintf(ref_path, sizeof(ref_path), "%s/reference_output_cpu.f32.bin", tensors_dir);

  TensorShape shapes[8];
  int n_shapes = load_shapes(shapes_path, shapes, 8);
  TensorShape *pv_shape, *mask_shape, *ref_shape;
  if (!find_shape(shapes, n_shapes, "pixel_values", &pv_shape) ||
      !find_shape(shapes, n_shapes, "pixel_attention_mask", &mask_shape) ||
      !find_shape(shapes, n_shapes, "reference_output_cpu", &ref_shape)) {
    fprintf(stderr, "FATAL: missing expected shape entries in %s\n", shapes_path);
    return 1;
  }

  int64_t ref_count = num_elements(ref_shape);
  float* pixel_values = (float*)read_binary_file(pv_path, (size_t)num_elements(pv_shape) * sizeof(float));
  unsigned char* pixel_mask = (unsigned char*)read_binary_file(mask_path, (size_t)num_elements(mask_shape));
  float* reference_output = (float*)read_binary_file(ref_path, (size_t)ref_count * sizeof(float));

  const OrtApiBase* api_base = OrtGetApiBase();
  g_api = api_base->GetApi(ORT_API_VERSION);
  if (!g_api) {
    fprintf(stderr, "FATAL: OrtGetApiBase()->GetApi() returned NULL\n");
    return 1;
  }

  OrtEnv* env = NULL;
  CHECK_STATUS(g_api->CreateEnv(ORT_LOGGING_LEVEL_WARNING, "granite-docling-vision-encoder", &env));

  // Run 1: CPU (self-consistency check -- this ONNX file, on THIS device's
  // CPU, should match the reference computed on Overmind's CPU almost
  // exactly; a real mismatch here would mean something ARM/build-specific
  // is already wrong before NNAPI is even involved).
  {
    OrtSessionOptions* options = NULL;
    CHECK_STATUS(g_api->CreateSessionOptions(&options));
    run_and_check("CPU", env, model_path, options, pixel_values, pv_shape, pixel_mask, mask_shape,
                  reference_output, ref_count);
    g_api->ReleaseSessionOptions(options);
  }

  // Run 2: NNAPI with CPU fallback explicitly disabled -- the real test,
  // matching Phase C's MobileNet acceptance criteria (Section 6.2 of the
  // catalog v4 design notes): an "accelerated" result must not be able to
  // secretly be NNAPI's own nnapi-reference CPU implementation.
  {
    OrtSessionOptions* options = NULL;
    CHECK_STATUS(g_api->CreateSessionOptions(&options));
    CHECK_STATUS(OrtSessionOptionsAppendExecutionProvider_Nnapi(options, NNAPI_FLAG_CPU_DISABLED));
    run_and_check("NNAPI(no-cpu)", env, model_path, options, pixel_values, pv_shape, pixel_mask,
                  mask_shape, reference_output, ref_count);
    g_api->ReleaseSessionOptions(options);
  }

  // Run 3: NNAPI with CPU fallback allowed -- isolates whether
  // CPU_DISABLED specifically breaks something, versus NNAPI integration
  // failing outright regardless of the flag (same pattern as Phase C).
  {
    OrtSessionOptions* options = NULL;
    CHECK_STATUS(g_api->CreateSessionOptions(&options));
    CHECK_STATUS(OrtSessionOptionsAppendExecutionProvider_Nnapi(options, NNAPI_FLAG_USE_NONE));
    run_and_check("NNAPI(cpu-ok)", env, model_path, options, pixel_values, pv_shape, pixel_mask,
                  mask_shape, reference_output, ref_count);
    g_api->ReleaseSessionOptions(options);
  }

  free(pixel_values);
  free(pixel_mask);
  free(reference_output);
  g_api->ReleaseEnv(env);
  return 0;
}
