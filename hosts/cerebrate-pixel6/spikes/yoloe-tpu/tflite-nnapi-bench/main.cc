// TFLite NNAPI bench for the Edge TPU (lane Step 2B, TPU path 2): runs one
// .tflite model with the classic TFLite C API either on the CPU (no
// delegate) or through the NNAPI delegate pinned to google-edgetpu with
// NNAPI's own CPU fallback disallowed (ops the TPU can't take stay on TFLite's
// CPU kernels). Inputs are raw tensor bytes from files, outputs are written
// raw. Reports load time (includes the TPU compile), first-run time and the
// steady-state median.
//
// usage: tflite-nnapi-bench <model.tflite> <cpu|tpu|tpu16> <inputs.txt> <out_dir> <iterations>
//   tpu16: as tpu, with the delegate's allow_fp16 (NNAPI relaxed fp32 -> fp16)
//   inputs.txt: one sample per line, comma-separated files, one per input
// Environment (added for the compilation-cache test, edgesam-tpu):
//   NNAPI_CACHE_DIR, NNAPI_MODEL_TOKEN  set the delegate's cache_dir and
//     model_token (NNAPI compilation caching); both or neither
//   RELOADS=n  afterwards destroy and recreate interpreter + delegate n times
//     in this process, timing each load, and write each reload's outputs for
//     one pass over the inputs to <out_dir>/reload<r>/
#include <stdio.h>
#include <sys/stat.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <algorithm>
#include <string>
#include <vector>

#include "tensorflow/lite/c/c_api.h"
#include "tensorflow/lite/delegates/nnapi/nnapi_delegate_c_api.h"

static long now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

static bool read_file(const std::string& path, std::vector<char>* buf) {
  FILE* f = fopen(path.c_str(), "rb");
  if (!f) return false;
  fseek(f, 0, SEEK_END);
  long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  buf->resize(n);
  bool ok = fread(buf->data(), 1, n, f) == (size_t)n;
  fclose(f);
  return ok;
}

int main(int argc, char** argv) {
  if (argc < 6) {
    fprintf(stderr, "usage: %s <model.tflite> <cpu|tpu|tpu16> <inputs.txt> <out_dir> <iterations>\n", argv[0]);
    return 1;
  }
  const char* model_path = argv[1];
  bool fp16 = strcmp(argv[2], "tpu16") == 0;
  bool tpu = strcmp(argv[2], "tpu") == 0 || fp16;
  int iterations = atoi(argv[5]);

  std::vector<std::vector<std::string>> samples;
  FILE* lst = fopen(argv[3], "r");
  if (!lst) { fprintf(stderr, "FATAL: cannot open %s\n", argv[3]); return 1; }
  char line[8192];
  while (fgets(line, sizeof(line), lst)) {
    std::vector<std::string> files;
    for (char* tok = strtok(line, ",\n"); tok; tok = strtok(NULL, ",\n")) files.push_back(tok);
    if (!files.empty()) samples.push_back(files);
  }
  fclose(lst);

  const char* cache_dir = getenv("NNAPI_CACHE_DIR");
  const char* model_token = getenv("NNAPI_MODEL_TOKEN");
  if ((cache_dir == NULL) != (model_token == NULL)) { fprintf(stderr, "FATAL: set both NNAPI_CACHE_DIR and NNAPI_MODEL_TOKEN or neither\n"); return 1; }
  int reloads = getenv("RELOADS") ? atoi(getenv("RELOADS")) : 0;

  long t0 = now_us();
  TfLiteModel* model = TfLiteModelCreateFromFile(model_path);
  if (!model) { fprintf(stderr, "FATAL: cannot load %s\n", model_path); return 1; }
  TfLiteInterpreterOptions* options = NULL;
  TfLiteDelegate* delegate = NULL;
  TfLiteInterpreter* interp = NULL;
  auto create = [&]() -> bool {
    options = TfLiteInterpreterOptionsCreate();
    TfLiteInterpreterOptionsSetNumThreads(options, 4);
    if (tpu) {
      TfLiteNnapiDelegateOptions o = TfLiteNnapiDelegateOptionsDefault();
      o.accelerator_name = "google-edgetpu";
      o.execution_preference = TfLiteNnapiDelegateOptions::kSustainedSpeed;
      o.disallow_nnapi_cpu = 1;
      o.allow_fp16 = fp16 ? 1 : 0;
      o.cache_dir = cache_dir;
      o.model_token = model_token;
      delegate = TfLiteNnapiDelegateCreate(&o);
      if (!delegate) { fprintf(stderr, "FATAL: NNAPI delegate creation failed\n"); return false; }
      TfLiteInterpreterOptionsAddDelegate(options, delegate);
    }
    interp = TfLiteInterpreterCreate(model, options);
    if (!interp) { fprintf(stderr, "FATAL: interpreter creation failed\n"); return false; }
    if (TfLiteInterpreterAllocateTensors(interp) != kTfLiteOk) { fprintf(stderr, "FATAL: AllocateTensors failed\n"); return false; }
    return true;
  };
  auto destroy = [&]() {
    TfLiteInterpreterDelete(interp);
    TfLiteInterpreterOptionsDelete(options);
    if (delegate) TfLiteNnapiDelegateDelete(delegate);
    interp = NULL; options = NULL; delegate = NULL;
  };
  if (!create()) return 1;
  long load_us = now_us() - t0;

  int n_in = TfLiteInterpreterGetInputTensorCount(interp), n_out = TfLiteInterpreterGetOutputTensorCount(interp);
  for (int i = 0; i < n_in; i++) {
    const TfLiteTensor* t = TfLiteInterpreterGetInputTensor(interp, i);
    printf("  input %d: %zu bytes, type %d\n", i, TfLiteTensorByteSize(t), (int)TfLiteTensorType(t));
  }
  for (int i = 0; i < n_out; i++) {
    const TfLiteTensor* t = TfLiteInterpreterGetOutputTensor(interp, i);
    printf("  output %d: %zu bytes, type %d\n", i, TfLiteTensorByteSize(t), (int)TfLiteTensorType(t));
  }

  std::vector<std::vector<std::vector<char>>> data(samples.size());
  for (size_t s = 0; s < samples.size(); s++) {
    if ((int)samples[s].size() != n_in) { fprintf(stderr, "FATAL: sample %zu has %zu files, model has %d inputs\n", s, samples[s].size(), n_in); return 1; }
    data[s].resize(n_in);
    for (int i = 0; i < n_in; i++) {
      if (!read_file(samples[s][i], &data[s][i])) { fprintf(stderr, "FATAL: cannot read %s\n", samples[s][i].c_str()); return 1; }
      size_t want = TfLiteTensorByteSize(TfLiteInterpreterGetInputTensor(interp, i));
      if (data[s][i].size() != want) { fprintf(stderr, "FATAL: %s is %zu bytes, input %d wants %zu\n", samples[s][i].c_str(), data[s][i].size(), i, want); return 1; }
    }
  }

  std::vector<long> times;
  long first_us = -1;
  for (int k = 0; k < iterations; k++) {
    size_t s = (size_t)k % samples.size();
    long a = now_us();
    for (int i = 0; i < n_in; i++)
      TfLiteTensorCopyFromBuffer(TfLiteInterpreterGetInputTensor(interp, i), data[s][i].data(), data[s][i].size());
    if (TfLiteInterpreterInvoke(interp) != kTfLiteOk) { fprintf(stderr, "FATAL: Invoke failed\n"); return 1; }
    std::vector<char> out;
    for (int o = 0; o < n_out; o++) {
      const TfLiteTensor* t = TfLiteInterpreterGetOutputTensor(interp, o);
      out.resize(TfLiteTensorByteSize(t));
      TfLiteTensorCopyToBuffer(t, out.data(), out.size());
      if (k < (int)samples.size()) {
        char path[1024];
        snprintf(path, sizeof(path), "%s/%zu_o%d.bin", argv[4], s, o);
        FILE* f = fopen(path, "wb");
        if (f) { fwrite(out.data(), 1, out.size(), f); fclose(f); }
      }
    }
    long dt = now_us() - a;
    if (k == 0) first_us = dt;
    else times.push_back(dt);
  }
  std::sort(times.begin(), times.end());
  printf("model=%s accel=%s%s cache=%s load_us=%ld first_us=%ld iters=%zu median_us=%ld\n", model_path, tpu ? "tpu" : "cpu", fp16 ? "16" : "",
         cache_dir ? cache_dir : "-", load_us, first_us, times.size(), times.empty() ? -1L : times[times.size() / 2]);
  for (int r = 1; r <= reloads; r++) {
    destroy();
    long a = now_us();
    if (!create()) return 1;
    long reload_us = now_us() - a;
    std::string dir = std::string(argv[4]) + "/reload" + std::to_string(r);
    mkdir(dir.c_str(), 0777);
    long b = now_us();
    for (size_t s = 0; s < samples.size(); s++) {
      for (int i = 0; i < n_in; i++)
        TfLiteTensorCopyFromBuffer(TfLiteInterpreterGetInputTensor(interp, i), data[s][i].data(), data[s][i].size());
      if (TfLiteInterpreterInvoke(interp) != kTfLiteOk) { fprintf(stderr, "FATAL: Invoke failed (reload %d)\n", r); return 1; }
      for (int o = 0; o < n_out; o++) {
        const TfLiteTensor* t = TfLiteInterpreterGetOutputTensor(interp, o);
        std::vector<char> out(TfLiteTensorByteSize(t));
        TfLiteTensorCopyToBuffer(t, out.data(), out.size());
        char path[1024];
        snprintf(path, sizeof(path), "%s/%zu_o%d.bin", dir.c_str(), s, o);
        FILE* f = fopen(path, "wb");
        if (f) { fwrite(out.data(), 1, out.size(), f); fclose(f); }
      }
    }
    printf("reload=%d load_us=%ld pass_us=%ld\n", r, reload_us, now_us() - b);
  }
  destroy();
  TfLiteModelDelete(model);
  return 0;
}
