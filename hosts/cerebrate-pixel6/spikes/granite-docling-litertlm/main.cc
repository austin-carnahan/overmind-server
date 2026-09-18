// Granite-Docling LiteRT-LM comparison spike: evaluates
// litert-community/granite-docling-258M (an existing .litertlm
// conversion, INT8 vision tower + decoder) as an alternative to the
// proven llama.cpp / llama-mtmd-cli path documented in
// experiments/docling/README.md, for selective Docling enrichment of
// figures/equations/charts -- not full-page conversion.
//
// CPU only, per this spike's explicit scope (no GPU/NNAPI attempted).
// Images are pre-resized to exactly 512x512 with PIL's BILINEAR filter
// *before* being handed to this binary -- the model card explicitly
// warns that other resampling filters produce hallucinated output, so
// this spike does not trust or exercise any internal resize the engine
// might do; it hands over an already-correctly-sized PNG and nothing
// else changes size.
//
// One-shot, synchronous (litert_lm_session_generate_content, not the
// streaming API cerebrate-generate.cc uses in production) -- this is a
// comparison spike, not a persistent worker.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "engine.h"

static long now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

static void* read_file(const char* path, size_t* out_size) {
  FILE* f = fopen(path, "rb");
  if (!f) {
    fprintf(stderr, "FATAL: cannot open %s\n", path);
    exit(1);
  }
  fseek(f, 0, SEEK_END);
  long size = ftell(f);
  fseek(f, 0, SEEK_SET);
  void* buf = malloc((size_t)size);
  if (fread(buf, 1, (size_t)size, f) != (size_t)size) {
    fprintf(stderr, "FATAL: short read on %s\n", path);
    exit(1);
  }
  fclose(f);
  *out_size = (size_t)size;
  return buf;
}

int main(int argc, char** argv) {
  if (argc < 4) {
    fprintf(stderr, "usage: %s <model.litertlm> <image_512x512.png> <prompt>\n", argv[0]);
    return 1;
  }
  const char* model_path = argv[1];
  const char* image_path = argv[2];
  const char* prompt = argv[3];

  litert_lm_set_min_log_level(kLiteRtLmLogSeverityWarning);

  fprintf(stderr, "loading engine model=%s backend=cpu vision_backend=cpu ...\n", model_path);
  LiteRtLmEngineSettings* settings =
      litert_lm_engine_settings_create(model_path, "cpu", "cpu", NULL);
  if (!settings) {
    fprintf(stderr, "FATAL: engine_settings_create failed\n");
    return 1;
  }
  litert_lm_engine_settings_set_max_num_images(settings, 1);

  long t_load0 = now_us();
  LiteRtLmEngine* engine = litert_lm_engine_create(settings);
  long t_load1 = now_us();
  if (!engine) {
    fprintf(stderr, "FATAL: engine_create failed\n");
    return 1;
  }
  fprintf(stderr, "engine loaded in %ld us\n", t_load1 - t_load0);

  LiteRtLmSession* session = litert_lm_engine_create_session(engine, NULL);
  if (!session) {
    fprintf(stderr, "FATAL: session_create failed\n");
    return 1;
  }

  size_t image_size = 0;
  void* image_bytes = read_file(image_path, &image_size);
  fprintf(stderr, "image: %s (%zu bytes)\n", image_path, image_size);

  LiteRtLmInputData* image_input =
      litert_lm_input_data_create(kLiteRtLmInputDataTypeImage, image_bytes, image_size);
  LiteRtLmInputData* text_input = litert_lm_input_data_create(
      kLiteRtLmInputDataTypeText, prompt, strlen(prompt));
  if (!image_input || !text_input) {
    fprintf(stderr, "FATAL: input_data_create failed (image=%p text=%p)\n",
            (void*)image_input, (void*)text_input);
    return 1;
  }
  const LiteRtLmInputData* inputs[2] = {image_input, text_input};

  long t_run0 = now_us();
  LiteRtLmResponses* responses = litert_lm_session_generate_content(session, inputs, 2);
  long t_run1 = now_us();

  if (!responses) {
    fprintf(stderr, "FATAL: generate_content returned NULL\n");
    return 1;
  }

  int n = litert_lm_responses_get_num_candidates(responses);
  fprintf(stderr, "generate_us=%ld num_candidates=%d\n", t_run1 - t_run0, n);
  for (int i = 0; i < n; i++) {
    const char* text = litert_lm_responses_get_response_text_at(responses, i);
    printf("=== candidate %d ===\n%s\n", i, text ? text : "(null)");
  }

  litert_lm_responses_delete(responses);
  litert_lm_input_data_delete(image_input);
  litert_lm_input_data_delete(text_input);
  free(image_bytes);
  return 0;
}
