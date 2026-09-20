// cerebrate-gguf: a Cerebrate execution worker for GGUF-format models
// running through the llama.cpp runtime -- named for the artifact/runtime
// lane (matches MLServer's `llama_cpp` runtime name), not a model family,
// so it stays the right name for Granite-Docling, Qwen, Gemma, SmolVLM,
// or an actual LLaMA model alike.
//
// Stage 2 (Doclet Service V3): a persistent-transport wrapper around
// `llama-mtmd-cli`, not a `llama-server` adapter. `llama-server`'s
// multimodal serving path is confirmed broken for Granite-Docling
// (experiments/docling/README.md's decisive /completion test) --
// `llama-mtmd-cli --image` is the only path with proven-correct output.
// This binary binds and listens like cerebrate-infer/cerebrate-generate
// (so cerebrate-supervisor's readiness probe and idempotent lifecycle
// work identically), but does the actual work by forking a fresh
// `llama-mtmd-cli` process per request rather than holding a model
// loaded in-process. A slow path (~1m44s per image, almost entirely
// vision encoding on this device -- see the experiment's timing note),
// not a hot one; correctness and lifecycle parity with the other
// workers matters far more here than latency.
//
// llama-mtmd-cli and its shared libraries are NOT staged flat in
// /data/local/tmp like model files are -- they're auxiliary binaries
// this worker hardcodes the path to, not a client-supplied "model"
// subject to cerebrate-supervisor's model_path_is_approved() check.
// Only the GGUF model/mmproj paths (client-supplied via START) go
// through that flat-file validation.
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define LLAMA_MTMD_CLI "/data/local/tmp/llamacpp/llama-mtmd-cli"
#define LLAMACPP_LIB_DIR "/data/local/tmp/llamacpp"
#define STAGING_DIR "/data/local/tmp"

#define FRAME_DATA 0   // generated text (single chunk -- llama-mtmd-cli isn't
                        // streamed here, unlike cerebrate-generate)
#define FRAME_DONE 1   // successful end-of-stream, empty payload
#define FRAME_ERROR 2  // failure description as the payload

#define MAX_IMAGE_BYTES (16 * 1024 * 1024)
#define MAX_PROMPT_BYTES (16 * 1024)
#define MAX_OUTPUT_BYTES (1 * 1024 * 1024)

static long now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

// Set once at startup / per-accept so the forked llama-mtmd-cli child can
// close its inherited copies before exec -- otherwise the exec'd process
// holds a duplicate of the listening socket (and the current client
// connection) open for its entire lifetime, since fork() duplicates all
// open fds and execl() doesn't close non-FD_CLOEXEC ones. Found the hard
// way (Stage 4, 2026-09-18): killing cerebrate-gguf left port 8768
// listening anyway, attributed to the orphaned llama-mtmd-cli process,
// which blocked every subsequent START. cerebrate-supervisor.cc's own
// header comment already documents this exact pitfall for its own
// worker-launch fork() -- this was the same bug, just in a second place.
static int g_listen_fd = -1;
static int g_current_client_fd = -1;

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

static int send_frame(int fd, uint8_t type, const char* payload, size_t len) {
  uint32_t len_be = htonl((uint32_t)len);
  if (write_full(fd, &type, 1) != 0) return -1;
  if (write_full(fd, &len_be, 4) != 0) return -1;
  if (len > 0 && write_full(fd, payload, len) != 0) return -1;
  return 0;
}

// Runs llama-mtmd-cli once, synchronously, capturing its stdout in full.
// image_path may be NULL for a text-only request (kept general per the
// design's "future compatible GGUF models reuse this worker" goal, even
// though Granite-Docling always sends an image today). Returns 0 and
// fills *out_text/*out_len on success (process exited 0); returns -1 and
// fills err on failure (spawn/exec/exit-code failure or output overflow).
static int run_llama_mtmd_cli(const char* model_path, const char* mmproj_path,
                               const char* image_path, const char* prompt,
                               char* out_text, size_t out_cap, size_t* out_len,
                               char* err, size_t err_cap) {
  int pipe_fd[2];
  if (pipe(pipe_fd) != 0) {
    snprintf(err, err_cap, "pipe() failed: %s", strerror(errno));
    return -1;
  }

  pid_t pid = fork();
  if (pid < 0) {
    snprintf(err, err_cap, "fork() failed: %s", strerror(errno));
    close(pipe_fd[0]);
    close(pipe_fd[1]);
    return -1;
  }

  if (pid == 0) {
    // Close inherited fds first -- see g_listen_fd/g_current_client_fd
    // comment above. Must happen before touching stdout/exec.
    if (g_listen_fd >= 0) close(g_listen_fd);
    if (g_current_client_fd >= 0) close(g_current_client_fd);

    // Child: stdout -> pipe write end, stderr -> a log file (llama.cpp's
    // own progress/timing logs go there, matching cerebrate-supervisor's
    // convention of one <worker>.supervisor.log per worker rather than
    // dropping them).
    close(pipe_fd[0]);
    dup2(pipe_fd[1], STDOUT_FILENO);
    close(pipe_fd[1]);
    int log_fd = open(STAGING_DIR "/llama-mtmd-cli.log", O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (log_fd >= 0) {
      dup2(log_fd, STDERR_FILENO);
      close(log_fd);
    }

    // Combine llama.cpp's own lib dir with the flat staging dir this
    // process itself was launched with (LD_LIBRARY_PATH=/data/local/tmp,
    // set by cerebrate-supervisor) -- llama-mtmd-cli's shared libraries
    // live in the former, not the latter.
    setenv("LD_LIBRARY_PATH", LLAMACPP_LIB_DIR ":" STAGING_DIR, 1);

    // --mmproj is required by llama-mtmd-cli unconditionally, even for a
    // text-only request with no --image -- found via the first-ever real
    // test of this branch (Stage 4, 2026-09-18): omitting it fails fast
    // with "ERR: Missing --mmproj argument", not a graceful text-only
    // fallback. This project has one worker (Granite-Docling) per model
    // process, always started with a real mmproj path (cerebrate-supervisor
    // requires one for any needs_mmproj worker), so this is always
    // available regardless of whether this particular request has an image.
    if (image_path != NULL) {
      execl(LLAMA_MTMD_CLI, LLAMA_MTMD_CLI, "-m", model_path, "--mmproj",
            mmproj_path, "--image", image_path, "-p", prompt, "-n", "2048",
            "--temp", "0", (char*)NULL);
    } else {
      execl(LLAMA_MTMD_CLI, LLAMA_MTMD_CLI, "-m", model_path, "--mmproj",
            mmproj_path, "-p", prompt, "-n", "2048", "--temp", "0", (char*)NULL);
    }
    _exit(127);  // execl failed
  }

  // Parent: read the child's stdout to completion, then reap it. Order
  // matters -- draining the pipe first avoids a deadlock if the child
  // writes more than the pipe buffer before exiting.
  close(pipe_fd[1]);
  size_t total = 0;
  int overflow = 0;
  while (1) {
    if (total >= out_cap - 1) {
      overflow = 1;
      // Keep draining so the child doesn't block on a full pipe, but
      // stop copying into out_text.
      char discard[4096];
      if (read(pipe_fd[0], discard, sizeof(discard)) <= 0) break;
      continue;
    }
    ssize_t n = read(pipe_fd[0], out_text + total, out_cap - 1 - total);
    if (n <= 0) break;
    total += (size_t)n;
  }
  close(pipe_fd[0]);
  out_text[total] = '\0';

  int status;
  waitpid(pid, &status, 0);

  if (overflow) {
    snprintf(err, err_cap, "llama-mtmd-cli output exceeded %zu bytes", out_cap);
    return -1;
  }
  if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
    int code = WIFEXITED(status) ? WEXITSTATUS(status) : -WTERMSIG(status);
    snprintf(err, err_cap, "llama-mtmd-cli exited with code %d (see " STAGING_DIR
                            "/llama-mtmd-cli.log)", code);
    return -1;
  }

  *out_len = total;
  return 0;
}

int main(int argc, char** argv) {
  if (argc < 4) {
    fprintf(stderr, "usage: %s <model.gguf> <mmproj.gguf> <port>\n", argv[0]);
    return 1;
  }
  const char* model_path = argv[1];
  const char* mmproj_path = argv[2];
  int port = atoi(argv[3]);

  struct stat st;
  if (stat(model_path, &st) != 0) {
    fprintf(stderr, "FATAL: model file not found: %s\n", model_path);
    return 1;
  }
  if (stat(mmproj_path, &st) != 0) {
    fprintf(stderr, "FATAL: mmproj file not found: %s\n", mmproj_path);
    return 1;
  }
  if (stat(LLAMA_MTMD_CLI, &st) != 0) {
    fprintf(stderr, "FATAL: llama-mtmd-cli not found at " LLAMA_MTMD_CLI "\n");
    return 1;
  }

  int srv = socket(AF_INET, SOCK_STREAM, 0);
  g_listen_fd = srv;
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

  fprintf(stderr, "READY model=%s mmproj=%s port=%d\n", model_path, mmproj_path, port);

  // Request wire format: [4B BE image_len][image bytes][4B BE prompt_len]
  // [prompt bytes]. image_len == 0 means a text-only request (no --image
  // flag passed to llama-mtmd-cli). Response: cerebrate-generate's typed
  // frame protocol (FRAME_DATA/FRAME_DONE/FRAME_ERROR), one FRAME_DATA
  // covering the whole output since llama-mtmd-cli isn't invoked in a
  // streaming mode here.
  char* image_buf = (char*)malloc(MAX_IMAGE_BYTES);
  char* prompt_buf = (char*)malloc(MAX_PROMPT_BYTES + 1);
  char* out_buf = (char*)malloc(MAX_OUTPUT_BYTES);
  long request_id = 0;

  while (1) {
    int client = accept(srv, NULL, NULL);
    if (client < 0) continue;
    g_current_client_fd = client;

    struct timeval recv_timeout = {30, 0};
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &recv_timeout, sizeof(recv_timeout));

    while (1) {
      uint32_t image_len_be;
      if (read_full(client, &image_len_be, 4) != 0) break;
      uint32_t image_len = ntohl(image_len_be);
      if (image_len > MAX_IMAGE_BYTES) break;
      if (image_len > 0 && read_full(client, image_buf, image_len) != 0) break;

      uint32_t prompt_len_be;
      if (read_full(client, &prompt_len_be, 4) != 0) break;
      uint32_t prompt_len = ntohl(prompt_len_be);
      if (prompt_len == 0 || prompt_len > MAX_PROMPT_BYTES) break;
      if (read_full(client, prompt_buf, prompt_len) != 0) break;
      prompt_buf[prompt_len] = '\0';

      request_id++;
      long t0 = now_us();

      char image_path[128];
      image_path[0] = '\0';
      if (image_len > 0) {
        // PNG assumed -- the only format this worker's actual caller
        // (Docling Serve's picture_description_api, via the Stage 3
        // adapter) produces (see experiments/doclet-service Stage 1:
        // data:image/png;base64,... in every observed request). Not a
        // general-purpose image ingestion path.
        snprintf(image_path, sizeof(image_path), STAGING_DIR "/cerebrate-gguf-req-%d-%ld.png",
                 getpid(), request_id);
        int fd = open(image_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd < 0) {
          char err[128];
          snprintf(err, sizeof(err), "request_id=%ld failed to write temp image: %s",
                    request_id, strerror(errno));
          send_frame(client, FRAME_ERROR, err, strlen(err));
          continue;
        }
        write_full(fd, image_buf, image_len);
        close(fd);
      }

      size_t out_len = 0;
      char err[256];
      int rc = run_llama_mtmd_cli(model_path, mmproj_path,
                                   image_len > 0 ? image_path : NULL, prompt_buf,
                                   out_buf, MAX_OUTPUT_BYTES, &out_len, err, sizeof(err));

      if (image_path[0] != '\0') unlink(image_path);

      long t1 = now_us();
      fprintf(stderr, "request_id=%ld image_bytes=%u generate_us=%ld rc=%d\n",
              request_id, image_len, t1 - t0, rc);

      if (rc != 0) {
        send_frame(client, FRAME_ERROR, err, strlen(err));
      } else {
        send_frame(client, FRAME_DATA, out_buf, out_len);
        send_frame(client, FRAME_DONE, NULL, 0);
      }
    }
    close(client);
    g_current_client_fd = -1;
  }
  return 0;
}
