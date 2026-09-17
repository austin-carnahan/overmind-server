// Minimal persistent generation worker (Stage: Multi-Runtime Execution
// Plane, Phase 2/3). The Session Execution sibling to cerebrate-infer's
// Graph Execution -- a deliberately separate process, not a mode of that
// one. Loads a .litertlm model + creates the LiteRT-LM Engine ONCE, then
// serves TCP requests one at a time: create a session, generate content,
// return the result text + timing. No concurrency, no auth, no streaming
// yet (synchronous generate_content, matching the feasibility spike) --
// see the Multi-Runtime Execution Plane design notes for why those are
// deliberately deferred to later phases.
#include <arpa/inet.h>
#include <netinet/in.h>
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

static void send_framed(int fd, const char* text) {
  size_t len = strlen(text);
  uint32_t len_be = htonl((uint32_t)len);
  if (write_full(fd, &len_be, 4) != 0) return;
  write_full(fd, text, len);
}

// Wire protocol: each request/response is a 4-byte big-endian length
// prefix followed by that many bytes of UTF-8 text. Unlike
// cerebrate-infer's fixed-size image tensor, prompt/response text is
// variable-length and may contain any byte value (including newlines),
// so a length prefix is used instead of line-delimited framing. This is
// a native-worker validation protocol, not the final Debian-facing wire
// format -- that's Phase 4's job.
#define MAX_PROMPT_BYTES (64 * 1024)

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

      LiteRtLmSession* session = litert_lm_engine_create_session(engine, NULL);
      if (!session) {
        free(prompt);
        char err[64];
        snprintf(err, sizeof(err), "ERROR request_id=%ld session_create_failed",
                  request_id);
        send_framed(client, err);
        continue;
      }

      LiteRtLmInputData* input =
          litert_lm_input_data_create(kLiteRtLmInputDataTypeText, prompt, len);
      free(prompt);

      const LiteRtLmInputData* inputs[1] = {input};
      LiteRtLmResponses* responses =
          litert_lm_session_generate_content(session, inputs, 1);
      long t1 = now_us();

      char err_buf[64];
      const char* text = NULL;
      if (responses && litert_lm_responses_get_num_candidates(responses) > 0) {
        text = litert_lm_responses_get_response_text_at(responses, 0);
      }
      if (!text) {
        snprintf(err_buf, sizeof(err_buf), "ERROR request_id=%ld generate_failed",
                  request_id);
        text = err_buf;
      }

      fprintf(stderr, "request_id=%ld generate_us=%ld response_bytes=%zu\n",
              request_id, t1 - t0, strlen(text));
      send_framed(client, text);

      if (responses) litert_lm_responses_delete(responses);
      litert_lm_input_data_delete(input);
      litert_lm_session_delete(session);
    }
    close(client);
  }
  return 0;
}
