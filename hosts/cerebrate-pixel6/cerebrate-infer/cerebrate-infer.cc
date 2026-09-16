// Minimal persistent inference worker (Stage 4C).
// Loads model + creates NNAPI delegate (google-edgetpu forced) ONCE, then
// serves one TCP request at a time: run inference, return result + timing.
// No concurrency, no scheduler, no auth — deliberately tiny.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "tensorflow/lite/c/c_api.h"
#include "tensorflow/lite/delegates/nnapi/nnapi_delegate_c_api.h"

static long now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

int main(int argc, char** argv) {
  if (argc < 3) {
    fprintf(stderr, "usage: %s <model.tflite> <port>\n", argv[0]);
    return 1;
  }
  const char* model_path = argv[1];
  int port = atoi(argv[2]);

  // --- Load once ---
  TfLiteModel* model = TfLiteModelCreateFromFile(model_path);
  if (!model) {
    fprintf(stderr, "FATAL: failed to load model %s\n", model_path);
    return 1;
  }

  TfLiteNnapiDelegateOptions nnapi_opts = TfLiteNnapiDelegateOptionsDefault();
  nnapi_opts.accelerator_name = "google-edgetpu";
  nnapi_opts.execution_preference = TfLiteNnapiDelegateOptions::kSustainedSpeed;
  TfLiteDelegate* nnapi_delegate = TfLiteNnapiDelegateCreate(&nnapi_opts);
  if (!nnapi_delegate) {
    fprintf(stderr, "FATAL: failed to create NNAPI delegate\n");
    return 1;
  }

  TfLiteInterpreterOptions* options = TfLiteInterpreterOptionsCreate();
  TfLiteInterpreterOptionsAddDelegate(options, nnapi_delegate);
  TfLiteInterpreterOptionsSetNumThreads(options, 4);

  TfLiteInterpreter* interpreter = TfLiteInterpreterCreate(model, options);
  if (!interpreter) {
    fprintf(stderr, "FATAL: failed to create interpreter\n");
    return 1;
  }
  if (TfLiteInterpreterAllocateTensors(interpreter) != kTfLiteOk) {
    fprintf(stderr, "FATAL: failed to allocate tensors\n");
    return 1;
  }

  TfLiteTensor* input = TfLiteInterpreterGetInputTensor(interpreter, 0);
  size_t input_size = TfLiteTensorByteSize(input);
  unsigned char* dummy_input = (unsigned char*)calloc(1, input_size);
  // Deliberately tiny: one fixed all-zero input, not varying imagery —
  // this experiment measures the resident worker/accelerator, not model
  // accuracy on real data.
  for (size_t i = 0; i < input_size; i++) dummy_input[i] = (unsigned char)(i % 256);

  fprintf(stderr, "READY model=%s input_bytes=%zu delegate=google-edgetpu port=%d\n",
          model_path, input_size, port);

  // --- Serve forever, one request at a time ---
  int srv = socket(AF_INET, SOCK_STREAM, 0);
  int yes = 1;
  setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  struct sockaddr_in addr = {0};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = INADDR_ANY;
  addr.sin_port = htons(port);
  if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
    perror("bind");
    return 1;
  }
  listen(srv, 4);

  // Persistent-connection mode: a client opens ONE TCP connection and sends
  // many newline-delimited request triggers over it, reading one response
  // line per trigger. Removes the fresh-TCP-connect cost (measured at
  // ~22-24ms in the one-shot-per-request harness, versus ~1.2ms of actual
  // inference) so sustained-load runs can actually saturate the
  // accelerator instead of mostly measuring connection setup.
  long request_id = 0;
  while (1) {
    int client = accept(srv, NULL, NULL);
    if (client < 0) continue;

    char buf[256];
    ssize_t n;
    // Loop reading one line (one request trigger) at a time from this same
    // connection until the client closes it (read returns 0) or errors.
    while ((n = read(client, buf, sizeof(buf))) > 0) {
      request_id++;
      long handle_t0 = now_us();  // request-handling clock starts at read()

      long infer_t0 = now_us();
      TfLiteTensorCopyFromBuffer(input, dummy_input, input_size);
      TfLiteStatus status = TfLiteInterpreterInvoke(interpreter);
      long infer_t1 = now_us();

      char resp[512];
      if (status == kTfLiteOk) {
        const TfLiteTensor* output = TfLiteInterpreterGetOutputTensor(interpreter, 0);
        size_t out_size = TfLiteTensorByteSize(output);
        unsigned char* out_buf = (unsigned char*)malloc(out_size);
        TfLiteTensorCopyToBuffer(output, out_buf, out_size);
        // top class = argmax over the quantized uint8 output
        int top_idx = 0;
        unsigned char top_val = 0;
        for (size_t i = 0; i < out_size; i++) {
          if (out_buf[i] > top_val) { top_val = out_buf[i]; top_idx = (int)i; }
        }
        free(out_buf);
        long handle_t1 = now_us();  // stop clock just before writing the response
        snprintf(resp, sizeof(resp),
                 "request_id=%ld top_class=%d top_score=%u inference_us=%ld handle_us=%ld\n",
                 request_id, top_idx, top_val, infer_t1 - infer_t0, handle_t1 - handle_t0);
      } else {
        snprintf(resp, sizeof(resp), "request_id=%ld ERROR status=%d\n", request_id, status);
      }
      write(client, resp, strlen(resp));
    }
    close(client);
  }
  return 0;
}
