// cerebrate-supervisor: a tiny, purpose-built control service for starting
// and stopping cerebrate-infer/cerebrate-generate on the Android host.
//
// Phase B Stage 1 (see the Multi-Runtime Execution Plane and the
// Operational Model Catalog v4 design notes). Today MLServer's load()
// can only *connect* to a worker that already exists -- there is no
// execution channel from the Debian guest into the Android host it runs
// on (no SSH/ADB server there, no root, no /dev/vsock access as the
// unprivileged `shell` user -- see cerebrate-infer/README.md's "Why this
// still binds 0.0.0.0" section for why AVF-gateway TCP is the only real
// transport). This process is that missing execution channel: a small
// control server, reachable over the same AVF-gateway TCP path already
// proven for inference calls, exposing exactly START/STOP/STATUS/LIST
// against a fixed, known set of worker types and a fixed staging
// directory -- not an arbitrary remote shell.
//
// Wire protocol: one command per connection. Client sends a command name
// line, then zero or more "key: value" lines, terminated by either a
// blank line or connection EOF. Server writes exactly one text response,
// then closes -- no persistent connection, no framing beyond that.
//
//   START\nworker: generate\nmodel: /data/local/tmp/foo.litertlm\n\n
//   STOP\nworker: generate\n\n
//   STATUS\nworker: generate\n\n
//   LIST\n\n
//
// Doclet Service V3 Stage 2 added one worker ("gguf", cerebrate-gguf)
// and one wire field ("mmproj") -- a deliberate, bounded exception to
// this being otherwise frozen since Phase B, not a reopening of the
// protocol. cerebrate-gguf needs two GGUF paths (model + multimodal
// projector) where every existing worker needed at most one model plus
// a fixed enum (backend), so the wire protocol gained an optional
// "mmproj" key rather than overloading "model" or "backend":
//
//   START\nworker: gguf\nmodel: /data/local/tmp/foo.gguf\nmmproj: /data/local/tmp/foo-mmproj.gguf\n\n
//
// The Segmentation and Labeling Lane (Step 1) added three identical slots,
// "graph1".."graph3" (cerebrate-graph, ports 8769-8771), with no protocol
// change: one model per process means a pipeline needing several graphs
// resident at once (detector + SAM encoder + SAM decoder) needs several
// processes. Backend validation moved from a hardcoded cpu|gpu check to a
// per-slot allowed list, and the readiness wait became per-slot, since large
// ONNX models and NNAPI compilation can take far longer than 15s to load.
//
// cerebrate-hetero (TPU + GPU pipeline worker) added one slot, "hetero1"
// (port 8772), with no protocol change. Its "backend" field names one of a
// fixed set of profiles compiled in below; each profile carries its
// declared model and its complete command line, so a client still chooses
// only among fixed configurations -- never a path or an argument. The
// backend field widened from 8 to 32 characters for the profile names.
//
// Deliberately NOT built: arbitrary command execution, arbitrary binary
// paths, arbitrary ports, orphan-worker adoption after a supervisor
// restart, or automatic respawn-on-crash (see cerebrate-supervisor's
// README for what Stage 3 found and why auto-restart is deferred).
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define STAGING_DIR "/data/local/tmp"
#ifndef CONTROL_PORT
#define CONTROL_PORT 8767  // overridable at build time for a side-by-side test instance
#endif

enum WorkerState { STOPPED, RUNNING, EXITED };

// cerebrate-graph's execution providers (see cerebrate-graph.cc).
#define kGraphBackends "cpu,nnapi,nnapi16,xnnpack,webgpu"

// cerebrate-hetero profiles: the slot's "backend" names one; "model" must
// equal its declared model. argv follows the port (see cerebrate-hetero.cc).
// Every path is a flat file in STAGING_DIR, like every other worker's model.
struct HeteroProfile {
  const char* name;
  const char* model;
  const char* argv[10];  // NULL-terminated
};
static const HeteroProfile kHeteroProfiles[] = {
  {"yoloe-v8s-fast", STAGING_DIR "/yoloe-v8s-pf-backbone-tpu-fp32.tflite",
   {"tpu+gpu", STAGING_DIR "/libtensorflowlite_jni.so", STAGING_DIR "/yoloe-v8s-pf-backbone-tpu-fp32.tflite",
    STAGING_DIR "/yoloe-v8s-pf-head-gpu.tflite", "fp16acc32", STAGING_DIR "/yoloe-v8s-pf-gpu-nhwc.tflite", "fp16acc32", NULL}},
  {"yoloe-v8s-default", STAGING_DIR "/yoloe-v8s-pf-gpu-nhwc.tflite",
   {"gpu", STAGING_DIR "/yoloe-v8s-pf-gpu-nhwc.tflite", "fp32", NULL}},
};
static const int kNumHeteroProfiles = sizeof(kHeteroProfiles) / sizeof(kHeteroProfiles[0]);
#define kHeteroBackends "yoloe-v8s-fast,yoloe-v8s-default"

struct WorkerSlot {
  const char* name;         // protocol identifier, e.g. "infer"
  const char* binary_path;  // fixed, not client-supplied
  int fixed_port;           // fixed, not client-supplied
  int needs_backend;        // cerebrate-generate/cerebrate-graph take a backend; others don't
  int needs_mmproj;         // cerebrate-gguf takes a second GGUF (multimodal projector)
  const char* backends;     // comma-separated allowed backends when needs_backend
  int ready_timeout_ms;     // how long START waits for the worker's port to answer

  // Runtime state
  WorkerState state;
  pid_t pid;
  char model[256];
  char backend[32];
  char mmproj[256];
  int last_exit_code;

  // Optional, zero for the original slots
  int is_hetero;                // backend names a kHeteroProfiles entry
  const char* ld_library_path;  // NULL = STAGING_DIR
};

static WorkerSlot g_slots[] = {
  {"infer", STAGING_DIR "/cerebrate-infer", 8765, 0, 0, NULL, 15000, STOPPED, 0, "", "", "", 0, 0, NULL},
  {"generate", STAGING_DIR "/cerebrate-generate", 8766, 1, 0, "cpu,gpu", 15000, STOPPED, 0, "", "", "", 0, 0, NULL},
  {"gguf", STAGING_DIR "/cerebrate-gguf", 8768, 0, 1, NULL, 15000, STOPPED, 0, "", "", "", 0, 0, NULL},
  {"graph1", STAGING_DIR "/cerebrate-graph", 8769, 1, 0, kGraphBackends, 120000, STOPPED, 0, "", "", "", 0, 0, NULL},
  {"graph2", STAGING_DIR "/cerebrate-graph", 8770, 1, 0, kGraphBackends, 120000, STOPPED, 0, "", "", "", 0, 0, NULL},
  {"graph3", STAGING_DIR "/cerebrate-graph", 8771, 1, 0, kGraphBackends, 120000, STOPPED, 0, "", "", "", 0, 0, NULL},
  {"hetero1", STAGING_DIR "/cerebrate-hetero", 8772, 1, 0, kHeteroBackends, 120000, STOPPED, 0, "", "", "", 0,
   1, STAGING_DIR "/litert-2.3.0:" STAGING_DIR},
};

static const HeteroProfile* find_profile(const char* name) {
  for (int i = 0; i < kNumHeteroProfiles; i++)
    if (strcmp(kHeteroProfiles[i].name, name) == 0) return &kHeteroProfiles[i];
  return NULL;
}
static const int kNumSlots = sizeof(g_slots) / sizeof(g_slots[0]);

// Set once at startup / per-accept so a forked worker child can close its
// inherited copies before exec -- otherwise the exec'd process holds the
// listening socket and the client connection open for its whole lifetime
// (fork duplicates all fds, and execl() doesn't close non-FD_CLOEXEC ones),
// which means the client's read-until-EOF response loop never sees EOF.
static int g_listen_fd = -1;
static int g_current_client_fd = -1;

static WorkerSlot* find_slot(const char* name) {
  for (int i = 0; i < kNumSlots; i++) {
    if (strcmp(g_slots[i].name, name) == 0) return &g_slots[i];
  }
  return NULL;
}

// Non-blockingly reap any worker that has exited, so STATUS/LIST reflect
// crashes even if nothing explicitly stopped them.
static void reap_all(void) {
  for (int i = 0; i < kNumSlots; i++) {
    WorkerSlot* s = &g_slots[i];
    if (s->state != RUNNING) continue;
    int status;
    pid_t r = waitpid(s->pid, &status, WNOHANG);
    if (r == s->pid) {
      s->state = EXITED;
      s->last_exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : -WTERMSIG(status);
    }
  }
}

// Least-privilege model-path check: must be a flat file directly inside
// the one approved staging directory (matches Stage 3's stage-model
// layout) -- no traversal, no subdirectories, no arbitrary filesystem
// access on the supervisor's behalf.
static int model_path_is_approved(const char* path) {
  size_t prefix_len = strlen(STAGING_DIR "/");
  if (strncmp(path, STAGING_DIR "/", prefix_len) != 0) return 0;
  const char* rest = path + prefix_len;
  if (rest[0] == '\0') return 0;
  if (strstr(rest, "..") != NULL) return 0;
  if (strchr(rest, '/') != NULL) return 0;  // no subdirectories
  return 1;
}

// Exact match against one entry of the slot's comma-separated list.
static int backend_is_allowed(const WorkerSlot* s, const char* backend) {
  if (s->backends == NULL || backend[0] == '\0') return 0;
  size_t len = strlen(backend);
  const char* p = s->backends;
  while (*p) {
    const char* comma = strchr(p, ',');
    size_t entry_len = comma ? (size_t)(comma - p) : strlen(p);
    if (entry_len == len && strncmp(p, backend, len) == 0) return 1;
    if (!comma) break;
    p = comma + 1;
  }
  return 0;
}

static int connect_probe(int port, int timeout_ms) {
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  if (fd < 0) return 0;
  struct sockaddr_in addr = {0};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(port);
  inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
  struct timeval tv = {timeout_ms / 1000, (timeout_ms % 1000) * 1000};
  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
  int ok = (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) == 0);
  close(fd);
  return ok;
}

static void wait_for_ready(WorkerSlot* s, char* out, size_t out_len) {
  const int kTotalMs = s->ready_timeout_ms, kStepMs = 200;
  int waited = 0;
  while (waited < kTotalMs) {
    // A worker that fails fast (bad model path, etc.) shows up as EXITED
    // long before the readiness timeout -- don't wait out the full window.
    reap_all();
    if (s->state != RUNNING) {
      snprintf(out, out_len, "ERROR: worker exited during startup (code=%d)\n", s->last_exit_code);
      return;
    }
    if (connect_probe(s->fixed_port, 200)) {
      snprintf(out, out_len, "OK: started pid=%d port=%d\n", s->pid, s->fixed_port);
      return;
    }
    usleep(kStepMs * 1000);
    waited += kStepMs;
  }
  snprintf(out, out_len,
           "ERROR: started (pid=%d) but not accepting connections on port %d after %dms; "
           "left running, check STATUS\n",
           s->pid, s->fixed_port, kTotalMs);
}

static void start_worker(const char* worker, const char* model, const char* backend,
                          const char* mmproj, char* out, size_t out_len) {
  WorkerSlot* s = find_slot(worker);
  if (!s) {
    snprintf(out, out_len, "ERROR: unknown worker %s\n", worker);
    return;
  }
  if (model == NULL || model[0] == '\0') {
    snprintf(out, out_len, "ERROR: START requires a model field\n");
    return;
  }
  if (!model_path_is_approved(model)) {
    snprintf(out, out_len, "ERROR: model path not approved: %s\n", model);
    return;
  }
  if (s->needs_backend && !backend_is_allowed(s, backend)) {
    snprintf(out, out_len, "ERROR: worker %s requires backend one of %s\n", worker, s->backends);
    return;
  }
  const HeteroProfile* profile = NULL;
  if (s->is_hetero) {
    profile = find_profile(backend);
    if (!profile || strcmp(model, profile->model) != 0) {
      snprintf(out, out_len, "ERROR: worker %s profile %s requires model %s\n", worker, backend,
               profile ? profile->model : "(unknown profile)");
      return;
    }
    for (int a = 0; profile->argv[a]; a++) {
      struct stat pst;
      if (strncmp(profile->argv[a], STAGING_DIR "/", strlen(STAGING_DIR "/")) == 0 && stat(profile->argv[a], &pst) != 0) {
        snprintf(out, out_len, "ERROR: profile %s file not found: %s\n", backend, profile->argv[a]);
        return;
      }
    }
  }
  if (s->needs_mmproj) {
    if (mmproj == NULL || mmproj[0] == '\0') {
      snprintf(out, out_len, "ERROR: worker %s requires an mmproj field\n", worker);
      return;
    }
    if (!model_path_is_approved(mmproj)) {
      snprintf(out, out_len, "ERROR: mmproj path not approved: %s\n", mmproj);
      return;
    }
  }
  struct stat st;
  if (stat(model, &st) != 0) {
    snprintf(out, out_len, "ERROR: model file not found: %s\n", model);
    return;
  }
  if (s->needs_mmproj && stat(mmproj, &st) != 0) {
    snprintf(out, out_len, "ERROR: mmproj file not found: %s\n", mmproj);
    return;
  }

  reap_all();
  if (s->state == RUNNING) {
    int same = strcmp(s->model, model) == 0 &&
               (!s->needs_backend || strcmp(s->backend, backend) == 0) &&
               (!s->needs_mmproj || strcmp(s->mmproj, mmproj) == 0);
    if (same) {
      snprintf(out, out_len, "OK: already running pid=%d port=%d (idempotent)\n", s->pid, s->fixed_port);
    } else {
      snprintf(out, out_len,
               "ERROR: worker %s already running with a different configuration "
               "(model=%s); STOP first\n",
               worker, s->model);
    }
    return;
  }

  // Pre-flight, not just post-fork readiness: our own bookkeeping says
  // this worker isn't running, but if something is already answering on
  // its fixed port, that's a real conflict (most likely an orphan left
  // behind by a previous supervisor process that never adopted it, or a
  // manually-launched instance) -- not "started successfully." Found
  // empirically (Phase B Stage 3): without this check, wait_for_ready()'s
  // connect_probe() can't tell "my new child is serving" apart from "an
  // unrelated orphan was already listening the whole time," since a slow
  // model load (NNAPI/LiteRT-LM init easily takes 1-2s) means the probe
  // succeeds against the *orphan* long before the new child even reaches
  // its own bind() call -- reporting a false OK while the real new child
  // silently fails on EADDRINUSE moments later.
  if (connect_probe(s->fixed_port, 200)) {
    snprintf(out, out_len,
             "ERROR: port %d already has an unmanaged listener (not started "
             "by this supervisor) -- refusing to start a second one; STOP "
             "won't help since this supervisor doesn't own it, investigate "
             "manually (e.g. lsof/ps on the device)\n",
             s->fixed_port);
    return;
  }

  pid_t pid = fork();
  if (pid < 0) {
    snprintf(out, out_len, "ERROR: fork failed: %s\n", strerror(errno));
    return;
  }
  if (pid == 0) {
    // Close inherited fds first -- see g_listen_fd/g_current_client_fd
    // comment above. Must happen before setsid/exec.
    if (g_listen_fd >= 0) close(g_listen_fd);
    if (g_current_client_fd >= 0) close(g_current_client_fd);
    // New session so this worker survives this connection (and the
    // supervisor's own controlling terminal, if any) going away.
    setsid();
    char log_path[300];
    snprintf(log_path, sizeof(log_path), STAGING_DIR "/%s.supervisor.log", worker);
    int log_fd = open(log_path, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (log_fd >= 0) {
      dup2(log_fd, 1);
      dup2(log_fd, 2);
      close(log_fd);
    }
    setenv("LD_LIBRARY_PATH", s->ld_library_path ? s->ld_library_path : STAGING_DIR, 1);
    char port_str[16];
    snprintf(port_str, sizeof(port_str), "%d", s->fixed_port);
    if (profile) {
      setenv("CEREBRATE_HETERO_PROFILE", profile->name, 1);
      setenv("CEREBRATE_HETERO_MODEL", profile->model, 1);
      const char* args[16];
      int n = 0;
      args[n++] = s->binary_path;
      args[n++] = port_str;
      for (int a = 0; profile->argv[a] && n < 15; a++) args[n++] = profile->argv[a];
      args[n] = NULL;
      execv(s->binary_path, (char* const*)args);
    } else if (s->needs_backend) {
      execl(s->binary_path, s->binary_path, model, backend, port_str, (char*)NULL);
    } else if (s->needs_mmproj) {
      execl(s->binary_path, s->binary_path, model, mmproj, port_str, (char*)NULL);
    } else {
      execl(s->binary_path, s->binary_path, model, port_str, (char*)NULL);
    }
    _exit(127);  // execl failed
  }

  // Parent
  s->pid = pid;
  s->state = RUNNING;
  strncpy(s->model, model, sizeof(s->model) - 1);
  s->model[sizeof(s->model) - 1] = '\0';
  if (s->needs_mmproj) {
    strncpy(s->mmproj, mmproj, sizeof(s->mmproj) - 1);
    s->mmproj[sizeof(s->mmproj) - 1] = '\0';
  }
  if (s->needs_backend) {
    strncpy(s->backend, backend, sizeof(s->backend) - 1);
    s->backend[sizeof(s->backend) - 1] = '\0';
  }
  wait_for_ready(s, out, out_len);
}

static void stop_worker(const char* worker, char* out, size_t out_len) {
  WorkerSlot* s = find_slot(worker);
  if (!s) {
    snprintf(out, out_len, "ERROR: unknown worker %s\n", worker);
    return;
  }
  reap_all();
  if (s->state != RUNNING) {
    snprintf(out, out_len, "OK: already stopped (idempotent)\n");
    return;
  }

  kill(s->pid, SIGTERM);
  const int kGraceMs = 5000, kStepMs = 100;
  int waited = 0;
  int exited = 0;
  while (waited < kGraceMs) {
    int status;
    if (waitpid(s->pid, &status, WNOHANG) == s->pid) {
      s->last_exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : -WTERMSIG(status);
      exited = 1;
      break;
    }
    usleep(kStepMs * 1000);
    waited += kStepMs;
  }
  if (!exited) {
    kill(s->pid, SIGKILL);
    int status;
    waitpid(s->pid, &status, 0);
    s->last_exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : -WTERMSIG(status);
  }
  s->state = STOPPED;
  snprintf(out, out_len, "OK: stopped%s\n", exited ? "" : " (SIGKILL after grace period)");
}

static void status_line(WorkerSlot* s, char* out, size_t out_len) {
  reap_all();
  switch (s->state) {
    case RUNNING:
      snprintf(out, out_len, "%s RUNNING pid=%d port=%d model=%s%s%s%s%s\n",
               s->name, s->pid, s->fixed_port, s->model,
               s->needs_backend ? " backend=" : "", s->needs_backend ? s->backend : "",
               s->needs_mmproj ? " mmproj=" : "", s->needs_mmproj ? s->mmproj : "");
      break;
    case EXITED:
      snprintf(out, out_len, "%s EXITED pid=%d exit_code=%d last_model=%s\n",
               s->name, s->pid, s->last_exit_code, s->model);
      break;
    default:
      snprintf(out, out_len, "%s STOPPED\n", s->name);
  }
}

static void handle_command(const char* cmd, const char* worker, const char* model,
                            const char* backend, const char* mmproj, char* out, size_t out_len) {
  if (strcmp(cmd, "START") == 0) {
    if (!worker[0]) { snprintf(out, out_len, "ERROR: START requires a worker field\n"); return; }
    start_worker(worker, model, backend[0] ? backend : "cpu", mmproj, out, out_len);
  } else if (strcmp(cmd, "STOP") == 0) {
    if (!worker[0]) { snprintf(out, out_len, "ERROR: STOP requires a worker field\n"); return; }
    stop_worker(worker, out, out_len);
  } else if (strcmp(cmd, "STATUS") == 0) {
    if (!worker[0]) { snprintf(out, out_len, "ERROR: STATUS requires a worker field\n"); return; }
    WorkerSlot* s = find_slot(worker);
    if (!s) { snprintf(out, out_len, "ERROR: unknown worker %s\n", worker); return; }
    status_line(s, out, out_len);
  } else if (strcmp(cmd, "LIST") == 0) {
    out[0] = '\0';
    for (int i = 0; i < kNumSlots; i++) {
      char line[300];
      status_line(&g_slots[i], line, sizeof(line));
      strncat(out, line, out_len - strlen(out) - 1);
    }
  } else {
    snprintf(out, out_len, "ERROR: unknown command %s\n", cmd);
  }
}

// Reads a request (command line + "key: value" lines) until a blank line
// or EOF. Parses into fixed output buffers -- deliberately not a general
// parser, since the accepted vocabulary is fixed and small.
static void read_request(int client, char* cmd, char* worker, char* model, char* backend,
                          char* mmproj) {
  cmd[0] = worker[0] = model[0] = backend[0] = mmproj[0] = '\0';
  char buf[4096];
  size_t total = 0;
  while (total < sizeof(buf) - 1) {
    ssize_t n = read(client, buf + total, sizeof(buf) - 1 - total);
    if (n <= 0) break;
    total += (size_t)n;
    buf[total] = '\0';
    if (strstr(buf, "\n\n") != NULL) break;
  }
  buf[total] = '\0';

  char* line = strtok(buf, "\n");
  int first = 1;
  while (line != NULL) {
    // Strip a trailing \r for clients that send CRLF.
    size_t len = strlen(line);
    if (len > 0 && line[len - 1] == '\r') line[len - 1] = '\0';
    if (first) {
      strncpy(cmd, line, 15);
      cmd[15] = '\0';
      first = 0;
    } else {
      char* colon = strchr(line, ':');
      if (colon) {
        *colon = '\0';
        char* key = line;
        char* val = colon + 1;
        while (*val == ' ') val++;
        if (strcmp(key, "worker") == 0) { strncpy(worker, val, 31); worker[31] = '\0'; }
        else if (strcmp(key, "model") == 0) { strncpy(model, val, 255); model[255] = '\0'; }
        else if (strcmp(key, "backend") == 0) { strncpy(backend, val, 31); backend[31] = '\0'; }
        else if (strcmp(key, "mmproj") == 0) { strncpy(mmproj, val, 255); mmproj[255] = '\0'; }
      }
    }
    line = strtok(NULL, "\n");
  }
}

int main(int argc, char** argv) {
  // Reap-friendly: never let a stopped/killed worker linger as a zombie
  // between explicit reap_all() calls either.
  signal(SIGPIPE, SIG_IGN);

  int srv = socket(AF_INET, SOCK_STREAM, 0);
  g_listen_fd = srv;
  int yes = 1;
  setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  struct sockaddr_in addr = {0};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = INADDR_ANY;
  addr.sin_port = htons(CONTROL_PORT);
  if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
    perror("bind");
    return 1;
  }
  listen(srv, 4);
  char worker_names[128] = "";
  for (int i = 0; i < kNumSlots; i++) {
    if (i > 0) strncat(worker_names, ",", sizeof(worker_names) - strlen(worker_names) - 1);
    strncat(worker_names, g_slots[i].name, sizeof(worker_names) - strlen(worker_names) - 1);
  }
  fprintf(stderr, "READY cerebrate-supervisor port=%d workers=%s\n", CONTROL_PORT, worker_names);

  while (1) {
    int client = accept(srv, NULL, NULL);
    if (client < 0) {
      reap_all();  // still reap on EINTR/spurious wakeups
      continue;
    }
    g_current_client_fd = client;
    struct timeval recv_timeout = {10, 0};
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &recv_timeout, sizeof(recv_timeout));

    char cmd[16], worker[32], model[256], backend[32], mmproj[256];
    read_request(client, cmd, worker, model, backend, mmproj);

    char response[2048];  // LIST: one status line per slot, seven slots
    if (cmd[0] == '\0') {
      snprintf(response, sizeof(response), "ERROR: empty request\n");
    } else {
      handle_command(cmd, worker, model, backend, mmproj, response, sizeof(response));
    }
    write(client, response, strlen(response));
    close(client);
    g_current_client_fd = -1;
  }
  return 0;
}
