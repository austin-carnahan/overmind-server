// TPU stage of cerebrate-hetero's pipeline: the TFLite 2.16.1 C API + NNAPI delegate
// (pinned to google-edgetpu, NNAPI CPU fallback disallowed, optional fp16
// relaxation), loaded *privately* with dlopen(RTLD_LOCAL) and called through
// function pointers, so it can share a process with LiteRT 2.3 (which exports
// the same TfLite* names). libtensorflowlite_jni.so has no dynamic
// relocations against those names, so its internal calls stay bound to itself.
// With a cache directory and token, the delegate uses NNAPI compilation
// caching: the G1 driver then loads a compiled model in ~0.2 s instead of
// recompiling (EdgeSAM's trunk: 43 s), and rejects a stale blob rather than
// reusing it (spikes/edgesam-tpu).
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "tensorflow/lite/c/c_api.h"
#include "tensorflow/lite/delegates/nnapi/nnapi_delegate_c_api.h"

namespace {
struct Api {
  decltype(&TfLiteModelCreateFromFile) ModelCreateFromFile;
  decltype(&TfLiteInterpreterOptionsCreate) OptionsCreate;
  decltype(&TfLiteInterpreterOptionsSetNumThreads) SetNumThreads;
  decltype(&TfLiteInterpreterOptionsAddDelegate) AddDelegate;
  decltype(&TfLiteNnapiDelegateOptionsDefault) NnapiDefault;
  decltype(&TfLiteNnapiDelegateCreate) NnapiCreate;
  decltype(&TfLiteInterpreterCreate) InterpreterCreate;
  decltype(&TfLiteInterpreterAllocateTensors) AllocateTensors;
  decltype(&TfLiteInterpreterGetInputTensor) GetInputTensor;
  decltype(&TfLiteInterpreterGetOutputTensorCount) GetOutputTensorCount;
  decltype(&TfLiteInterpreterGetOutputTensor) GetOutputTensor;
  decltype(&TfLiteTensorByteSize) TensorByteSize;
  decltype(&TfLiteTensorNumDims) TensorNumDims;
  decltype(&TfLiteTensorDim) TensorDim;
  decltype(&TfLiteTensorCopyFromBuffer) CopyFromBuffer;
  decltype(&TfLiteTensorCopyToBuffer) CopyToBuffer;
  decltype(&TfLiteInterpreterInvoke) Invoke;
} api;
TfLiteInterpreter* interp = nullptr;
}  // namespace

#define SYM(field, name)                                                  \
  api.field = (decltype(api.field))dlsym(h, name);                        \
  if (!api.field) { fprintf(stderr, "FATAL: dlsym %s\n", name); return 1; }

// cache_dir and model_token: both NULL (no compilation caching) or both set.
extern "C" int tpu_init(const char* lib, const char* model_path, int fp16, const char* cache_dir, const char* model_token) {
  void* h = dlopen(lib, RTLD_NOW | RTLD_LOCAL);
  if (!h) { fprintf(stderr, "FATAL: dlopen %s: %s\n", lib, dlerror()); return 1; }
  SYM(ModelCreateFromFile, "TfLiteModelCreateFromFile");
  SYM(OptionsCreate, "TfLiteInterpreterOptionsCreate");
  SYM(SetNumThreads, "TfLiteInterpreterOptionsSetNumThreads");
  SYM(AddDelegate, "TfLiteInterpreterOptionsAddDelegate");
  SYM(NnapiDefault, "TfLiteNnapiDelegateOptionsDefault");
  SYM(NnapiCreate, "TfLiteNnapiDelegateCreate");
  SYM(InterpreterCreate, "TfLiteInterpreterCreate");
  SYM(AllocateTensors, "TfLiteInterpreterAllocateTensors");
  SYM(GetInputTensor, "TfLiteInterpreterGetInputTensor");
  SYM(GetOutputTensorCount, "TfLiteInterpreterGetOutputTensorCount");
  SYM(GetOutputTensor, "TfLiteInterpreterGetOutputTensor");
  SYM(TensorByteSize, "TfLiteTensorByteSize");
  SYM(TensorNumDims, "TfLiteTensorNumDims");
  SYM(TensorDim, "TfLiteTensorDim");
  SYM(CopyFromBuffer, "TfLiteTensorCopyFromBuffer");
  SYM(CopyToBuffer, "TfLiteTensorCopyToBuffer");
  SYM(Invoke, "TfLiteInterpreterInvoke");
  TfLiteModel* model = api.ModelCreateFromFile(model_path);
  if (!model) { fprintf(stderr, "FATAL: cannot load %s\n", model_path); return 1; }
  TfLiteInterpreterOptions* o = api.OptionsCreate();
  api.SetNumThreads(o, 4);
  TfLiteNnapiDelegateOptions n = api.NnapiDefault();
  n.accelerator_name = "google-edgetpu";
  n.execution_preference = TfLiteNnapiDelegateOptions::kSustainedSpeed;
  n.disallow_nnapi_cpu = 1;
  n.allow_fp16 = fp16;
  n.cache_dir = cache_dir;
  n.model_token = model_token;
  TfLiteDelegate* d = api.NnapiCreate(&n);
  if (!d) { fprintf(stderr, "FATAL: NNAPI delegate\n"); return 1; }
  api.AddDelegate(o, d);
  interp = api.InterpreterCreate(model, o);
  if (!interp || api.AllocateTensors(interp) != kTfLiteOk) { fprintf(stderr, "FATAL: TPU interpreter\n"); return 1; }
  return 0;
}
extern "C" size_t tpu_input_bytes() { return api.TensorByteSize(api.GetInputTensor(interp, 0)); }
extern "C" int tpu_input_dims(int64_t* dims, int max_rank) {
  const TfLiteTensor* t = api.GetInputTensor(interp, 0);
  int rank = api.TensorNumDims(t);
  for (int d = 0; d < rank && d < max_rank; d++) dims[d] = api.TensorDim(t, d);
  return rank;
}
extern "C" int tpu_num_outputs() { return api.GetOutputTensorCount(interp); }
extern "C" size_t tpu_output_bytes(int k) { return api.TensorByteSize(api.GetOutputTensor(interp, k)); }
extern "C" int tpu_run(const void* in, void* const* outs) {
  if (api.CopyFromBuffer(api.GetInputTensor(interp, 0), in, tpu_input_bytes()) != kTfLiteOk) return 1;
  if (api.Invoke(interp) != kTfLiteOk) return 1;
  for (int k = 0; k < tpu_num_outputs(); k++)
    if (api.CopyToBuffer(api.GetOutputTensor(interp, k), outs[k], tpu_output_bytes(k)) != kTfLiteOk) return 1;
  return 0;
}
