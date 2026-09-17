// Minimal persistent generation worker (Stage: Multi-Runtime Execution
// Plane, Phase 2/3/streaming). The Session Execution sibling to
// cerebrate-infer's Graph Execution -- a deliberately separate process,
// not a mode of that one. Loads a .litertlm model + creates the
// LiteRT-LM Engine ONCE, then serves TCP requests one at a time: create
// a session, stream-generate content, relay each chunk as it's produced.
//
// Streaming update: uses litert_lm_session_generate_content_stream
// (not the earlier synchronous generate_content) as the ONLY native
// generation path now, so there is exactly one implementation instead
// of two side-by-side APIs. That call is non-blocking and invokes its
// callback from a LiteRT-LM-owned BACKGROUND THREAD, one call per
// chunk -- the first real multi-threading in this worker. A
// pthread mutex/condvar hands control back to the accept-loop thread
// once a chunk reports it's final (or errored). Whether a caller wants
// the full response buffered (today's /infer-equivalent behavior) or
// relayed incrementally is entirely the Debian adapter's decision, not
// something duplicated here.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#include "engine.h"

static long now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

// Reads exactly n bytes, or returns -1 on EOF/error/timeout.
static int read_full(int fd, void* buf, size_t n) {
  size_t got = 0;
  while (got < n) {
    ssize_t r = read(fd, (char*)buf + got, n - got);
    if (r <= 0) return -1;
    got += (size_t)r;
  }
  return 0;
}

static int write_full(int fd, const void* buf, size_t n) {
  size_t sent = 0;
  while (sent < n) {
    ssize_t w = write(fd, (const char*)buf + sent, n - sent);
    if (w <= 0) return -1;
    sent += (size_t)w;
  }
  return 0;
}

// Typed-frame protocol: [1-byte type][4-byte BE length][payload]. Replaces
// the earlier bare length-prefixed single response -- a breaking wire
// change, made deliberately while this worker has exactly one known
// consumer and is cheap to change, rather than later.
#define FRAME_DATA 0   // one generated text chunk
#define FRAME_DONE 1   // successful end-of-stream, empty payload
#define FRAME_ERROR 2  // failure description as the payload

#define MAX_PROMPT_BYTES (64 * 1024)

// The LiteRT-LM engine's own default max_num_tokens (total context budget:
// prompt + chat-template overhead + generated output) is undocumented and,
// empirically, far too small -- confirmed via a genuinely freshly-started
// process failing on its very first request, a short prompt, with "Max
// number of tokens reached." Set explicitly instead of trusting that
// default. 8192 is SmolLM2-135M-Instruct's own real max_position_embeddings
// (verified against its published config.json), not an arbitrary guess.
// Hardcoded per-binary for now, matching this worker's existing
// one-model-per-process design; revisit as a command-line argument (like
// model_path/backend/port already are) once Phase E stages a second model
// with a different real context window through this same binary.
#define MAX_NUM_TOKENS 8192

static int send_frame(int fd, uint8_t type, const char* payload, size_t len) {
  uint32_t len_be = htonl((uint32_t)len);
  if (write_full(fd, &type, 1) != 0) return -1;
  if (write_full(fd, &len_be, 4) != 0) return -1;
  if (len > 0 && write_full(fd, payload, len) != 0) return -1;
  return 0;
}

// Shared between the accept-loop thread (which blocks waiting) and the
// LiteRT-LM callback thread (which delivers chunks and signals done).
typedef struct {
  int client_fd;
  pthread_mutex_t mutex;
  pthread_cond_t cond;
  int done;          // set once the stream is final, errored, or the
                      // client connection died mid-stream
  int write_failed;  // set if writing a frame to the client failed --
                      // the connection is bad, stop serving it
} StreamContext;

static void stream_callback(void* callback_data, const LiteRtLmStreamChunk* chunk) {
  StreamContext* ctx = (StreamContext*)callback_data;

  // The chunk (and everything it points to) is only valid for the
  // duration of this call -- read what's needed immediately.
  const char* error = litert_lm_stream_chunk_get_error(chunk);
  const char* text = litert_lm_stream_chunk_get_text(chunk);
  bool final = litert_lm_stream_chunk_is_final(chunk);

  int rc = 0;
  if (error) {
    rc = send_frame(ctx->client_fd, FRAME_ERROR, error, strlen(error));
  } else if (text && text[0] != '\0') {
    rc = send_frame(ctx->client_fd, FRAME_DATA, text, strlen(text));
  }

  if (rc != 0) {
    pthread_mutex_lock(&ctx->mutex);
    ctx->write_failed = 1;
    ctx->done = 1;
    pthread_cond_signal(&ctx->cond);
    pthread_mutex_unlock(&ctx->mutex);
    return;
  }

  if (final || error) {
    if (!error) send_frame(ctx->client_fd, FRAME_DONE, NULL, 0);
    pthread_mutex_lock(&ctx->mutex);
    ctx->done = 1;
    pthread_cond_signal(&ctx->cond);
    pthread_mutex_unlock(&ctx->mutex);
  }
}

int main(int argc, char** argv) {
  if (argc < 4) {
    fprintf(stderr, "usage: %s <model.litertlm> <backend: cpu|gpu> <port>\n",
            argv[0]);
    return 1;
  }
  const char* model_path = argv[1];
  const char* backend = argv[2];
  int port = atoi(argv[3]);

  litert_lm_set_min_log_level(kLiteRtLmLogSeverityWarning);

  fprintf(stderr, "loading engine model=%s backend=%s ...\n", model_path,
          backend);
  LiteRtLmEngineSettings* settings =
      litert_lm_engine_settings_create(model_path, backend, NULL, NULL);
  if (!settings) {
    fprintf(stderr, "FATAL: engine_settings_create failed\n");
    return 1;
  }
  litert_lm_engine_settings_set_max_num_tokens(settings, MAX_NUM_TOKENS);

  // Explicit, not left to whatever litert_lm_engine_create_session(engine,
  // NULL) defaults to -- the model does apply its chat template either
  // way (verified: the "Max number of tokens reached" failure traced back
  // to sampling, not templating, see below), but there's no reason to
  // trust an undocumented default silently rather than state it.
  LiteRtLmSessionConfig* session_config = litert_lm_session_config_create();
  if (!session_config) {
    fprintf(stderr, "FATAL: session_config_create failed\n");
    return 1;
  }
  litert_lm_session_config_set_apply_prompt_template(session_config, true);

  // The real root cause of "Max number of tokens reached" on a fresh
  // process: litert_lm_engine_create_session(engine, NULL)'s default
  // sampler is (empirically) pure greedy (argmax) decoding, which for
  // this small model gets stuck in a deterministic repetition loop
  // ("I'm glad you found the information helpful." repeated thousands of
  // times, confirmed by capturing the raw stream directly) and never
  // reaches its own EOS token (the engine does report one configured
  // stop token -- this genuinely never gets sampled under pure greedy
  // decoding here). top-p/temperature sampling breaks the determinism.
  // This C API (v0.1.0) exposes RepetitionPenaltyConfig/NoRepeatNgramConfig
  // constructors but no setter that attaches either to a session/sampler
  // -- unfinished bindings, not something usable here yet.
  LiteRtLmSamplerParams* sampler_params =
      litert_lm_sampler_params_create(kLiteRtLmSamplerTypeTopP);
  if (!sampler_params) {
    fprintf(stderr, "FATAL: sampler_params_create failed\n");
    return 1;
  }
  // kLiteRtLmSamplerTypeTopP still validates k as positive (top-k
  // filtering runs before nucleus filtering internally) -- confirmed
  // empirically via "INVALID_ARGUMENT: k must be positive" when this was
  // left unset. 40 is a conventional top-k value, wide enough that top_p
  // is the effective constraint.
  litert_lm_sampler_params_set_top_k(sampler_params, 40);
  litert_lm_sampler_params_set_top_p(sampler_params, 0.9f);
  litert_lm_sampler_params_set_temperature(sampler_params, 0.7f);
  litert_lm_session_config_set_sampler_params(session_config, sampler_params);

  LiteRtLmEngine* engine = litert_lm_engine_create(settings);
  if (!engine) {
    fprintf(stderr, "FATAL: engine_create failed\n");
    return 1;
  }

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

  fprintf(stderr, "READY model=%s backend=%s port=%d\n", model_path, backend,
          port);

  long request_id = 0;
  while (1) {
    int client = accept(srv, NULL, NULL);
    if (client < 0) continue;

    // Same lesson as cerebrate-infer's SO_RCVTIMEO fix (Stage 5 Phase 4):
    // a client's network path can vanish without a clean FIN/RST, and
    // without a timeout a blocking read() on a dead connection would
    // wedge this whole (single-threaded, serial) worker forever.
    struct timeval recv_timeout = {30, 0};
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &recv_timeout,
               sizeof(recv_timeout));

    while (1) {
      uint32_t len_be;
      if (read_full(client, &len_be, 4) != 0) break;
      uint32_t len = ntohl(len_be);
      if (len == 0 || len > MAX_PROMPT_BYTES) break;

      char* prompt = (char*)malloc(len + 1);
      if (read_full(client, prompt, len) != 0) {
        free(prompt);
        break;
      }
      prompt[len] = '\0';

      request_id++;
      long t0 = now_us();

      LiteRtLmSession* session =
          litert_lm_engine_create_session(engine, session_config);
      if (!session) {
        free(prompt);
        char err[64];
        snprintf(err, sizeof(err), "request_id=%ld session_create_failed",
                  request_id);
        send_frame(client, FRAME_ERROR, err, strlen(err));
        continue;
      }

      LiteRtLmInputData* input =
          litert_lm_input_data_create(kLiteRtLmInputDataTypeText, prompt, len);
      free(prompt);
      const LiteRtLmInputData* inputs[1] = {input};

      StreamContext ctx;
      ctx.client_fd = client;
      ctx.done = 0;
      ctx.write_failed = 0;
      pthread_mutex_init(&ctx.mutex, NULL);
      pthread_cond_init(&ctx.cond, NULL);

      int start_rc = litert_lm_session_generate_content_stream(
          session, inputs, 1, stream_callback, &ctx);
      if (start_rc != 0) {
        char err[80];
        snprintf(err, sizeof(err),
                  "request_id=%ld generate_stream_start_failed rc=%d",
                  request_id, start_rc);
        send_frame(client, FRAME_ERROR, err, strlen(err));
      } else {
        pthread_mutex_lock(&ctx.mutex);
        while (!ctx.done) {
          pthread_cond_wait(&ctx.cond, &ctx.mutex);
        }
        pthread_mutex_unlock(&ctx.mutex);
      }

      pthread_mutex_destroy(&ctx.mutex);
      pthread_cond_destroy(&ctx.cond);

      long t1 = now_us();
      fprintf(stderr, "request_id=%ld generate_us=%ld write_failed=%d\n",
              request_id, t1 - t0, ctx.write_failed);

      litert_lm_input_data_delete(input);
      litert_lm_session_delete(session);

      if (ctx.write_failed) break;  // connection is bad, stop serving it
    }
    close(client);
  }
  return 0;
}
