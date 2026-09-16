# Pixel 6 inference node

**Status:** PARTIAL — see [status legend](README.md#status-legend); Stages
1-3 done. **Decision: adopt the Debian guest as the control plane**, with
carried-forward caveats (Terminal-app-force-stop is a confirmed single
point of failure; full-reboot recovery unverified; see Stage 3 below for
the complete list). **Stage 4C (persistent inference worker) is built and
working**: [`cerebrate-infer`](../hosts/cerebrate-pixel6/cerebrate-infer/README.md)
loads the model + creates the `google-edgetpu` NNAPI delegate once, then
serves repeated TCP requests from Debian with no per-request process spawn
— chosen over the newer LiteRT v2 API after directly benchmarking it
~13× slower on this specific (Tensor G1) hardware. Stage 4D (proper
duration-based thermal/throughput characterization) is next. See
[hosts/cerebrate-pixel6](../hosts/cerebrate-pixel6/README.md) for the host
inventory this doc feeds.

## Goal

Convert a factory-reset Pixel 6 into a dedicated always-on inference node
for the Overmind home network — the second member of the "cerebrate"
fleet/class (see the naming-convention section of the
[home DNS + reverse-proxy plan](2026-09-15-home-dns-reverse-proxy-plan.md)).
Stock Android 17, no SIM/Google account, unnecessary radios minimized,
Developer Options + USB/Wireless ADB enabled, Android's experimental Debian
Linux guest enabled. Stays a normal LAN device — remote access comes
through Overmind/Cerebrate subnet routing, not direct Tailscale enrollment.

Favor supported Android/Linux mechanisms over rooting or one-off hacks;
avoid undocumented tweaks unless they solve a demonstrated problem.

## Staged plan

1. **ADB baseline + appliance-readiness review** — identity/health/resources,
   thermal sensors, and a review of settings that could silently break an
   unattended appliance (Doze, stay-awake-while-charging, Wi-Fi power-save,
   Battery Saver, ADB persistence). Read-only discovery; any fix applied
   deliberately, not bundled in.
2. **Debian/Linux guest inspection** — first establish the actual headless
   access path into the guest (unknown going in: whether it's ADB-reachable
   at all, or only through the Terminal app's own UI), then kernel/arch,
   CPU/RAM/storage as seen from the guest, networking type, systemd vs.
   minimal init, `/dev` contents (GPU/DRM/accelerator visibility), package
   manager functionality, and reboot persistence.
3. **Control-plane decision and validation** — grew from a one-line
   judgment call into four bounded validation passes once real questions
   piled up: (1) unattended lifecycle behavior (screen-off, backgrounding,
   force-stop, network loss, reboot), (2) the compatibility boundary
   between this guest and stock Debian, (3) GPU/DRM/accelerator visibility,
   and (4) the real memory budget. **Result: adopt Debian as the control
   plane**, with several carried-forward risks (most notably: the Terminal
   app must never be force-stopped, and full-reboot recovery is untested)
   — see Stage 3 below for the complete decision and evidence.
4. **Minimal inference service + characterization** — smallest real
   workload placed wherever Stage 3 decided, measuring idle vs. sustained
   thermal/throttling/reliability/power behavior before adding more
   infrastructure.

## Stage 1 — done (2026-09-16)

Baseline captured (see host doc for the full snapshot) and two
appliance-readiness settings reviewed:

- **`stay_on_while_plugged_in`**: initially set to `7` (AC+USB+Wireless,
  matching Developer Options' own "Stay awake" toggle) on the mistaken
  assumption that it protected against Doze while charging — **reverted
  to `0` on 2026-09-16** once corrected: Doze specifically requires the
  device to be unplugged, stationary, and screen-off, and App Standby
  restrictions already lift while charging. Setting `7` bought nothing
  against Doze and instead kept the OLED lit continuously on a permanently
  plugged-in device — actively bad for heat, power draw, and burn-in on
  an appliance that's never meant to be looked at. Verified reverted via
  `settings get global stay_on_while_plugged_in`. This is unrelated to the
  Terminal app's own separate VM-level "Keep awake" setting (below), which
  still matters and is unaffected by this correction.
- **Wi-Fi power-save force-disable**: investigated, not applied. `cmd wifi
  help` has no power-related subcommand; the legacy
  `wifi_suspend_optimizations_enabled` global setting doesn't exist in this
  build's settings table at all — not defaulted off, genuinely absent,
  suggesting it's been removed from AOSP on this Android version rather
  than just unset. The real mechanism is a `WifiManager`
  `WIFI_MODE_FULL_HIGH_PERF` lock held by running code, not a device
  setting. Deferred to Stage 4: whatever persistent service gets built
  should acquire that lock itself, and its effect is verifiable afterward
  via `dumpsys wifi`'s `mPowerSaveDisableRequests` counter.

Real finding worth keeping for Stage 4: `dumpsys thermalservice` shows a
**dedicated TPU thermal sensor and cooling device**, distinct from CPU
big/mid/little and GPU (G3D) — the Tensor NPU is independently thermally
instrumented, which should make throttling measurements much more legible
than inferring from CPU temperature alone.

## Stage 2A — headless console access: negative result (2026-09-16)

Android 17 documents `adb shell vm console` as a way to attach to a running
VM's serial console. Tested against the Terminal app's actual Debian VM
(started once from the app UI, confirmed via `vm list`) — fails with
`Error: Failed to get VM with console`, **not** a tty/permission problem
(those were ruled out first: `vm info` reports the debug policy as
`DebugPolicy { adb: false, ... }`, and `vm list`'s own debug info shows
`hostConsoleName: None` for this VM). The Terminal app launches its VM
without registering a host-attachable console at all — this looks like a
deliberate property of how the app configures its VM, not a permission gap
`-t`/`-tt` could work around. **Conclusion: `vm console` is a dead end for
this specific VM on this device**, independent of screen-off/backgrounding
questions — there's no console to survive losing in the first place.

`vm list` while the VM is running:

```text
VirtualMachineDebugInfo {
    name: "debian",
    cid: 2048,
    hostConsoleName: None,
    ...
}
```

`cid: 2048` confirms vsock is genuinely in use (AVF's virtio-vsock, per the
user's third-transport note) — not yet explored further.

## Stage 2A (continued) — driving the Terminal app's own UI via `adb input`: works, but fragile

With no console path, the fallback was controlling the Terminal app's own
on-screen shell via `adb shell input text`/`input tap`, screenshot-verified
at each step (no reliable stdout capture — everything was confirmed by
`screencap`). This is **not** a real headless interface; it's a workaround
to bootstrap SSH, documented here because every failure mode is a real,
reusable finding:

- **`adb shell input text "multi word string"`** gets word-split by the
  *remote* Android shell before the `input` tool ever sees it — adb joins
  all `shell` arguments with spaces and hands the result to `/system/bin/sh
  -c` on the device, so unquoted spaces/`&&`/`;` in the string get
  reinterpreted remotely. A multi-word `&&`-joined command actually ran
  its second half as a literal Android shell command (visible as
  `/system/bin/sh: sudo: inaccessible or not found` — Android has no
  `sudo`), not as typed text at all. Fix: encode spaces as `%s` (the
  documented `input text` convention) and never pass shell metacharacters
  in the string.
- **Synthetic Enter key events don't reliably submit** in this WebView-based
  terminal. Tried `KEYCODE_ENTER` (66) and `KEYCODE_NUMPAD_ENTER` (160) —
  neither reliably submits a typed command, though text input itself lands
  fine. Tapping the *on-screen keyboard's actual Enter key* (real
  coordinates, real tap) worked exactly once out of many tries, then
  stopped working with no visible state difference — genuinely
  unreliable, not a coordinate bug. **Physically tapping Enter on the
  device was the only 100% reliable submission method the whole session.**
  Likely cause: this terminal handles Enter via its own JS/IME
  text-commit callback rather than standard dispatched `KeyEvent`s, so
  synthetic key events don't consistently reach it.
- Screenshot coordinates from the Read tool's *displayed* rendering need
  the stated multiplier (here, ×1.2) applied before use as real `adb input
  tap` coordinates — mixed this up once mid-session (tapped based on
  displayed-space numbers directly) and landed on the wrong settings row
  as a result. Always apply the multiplier.

**Practical implication for Stage 3**: if Debian becomes the normal control
plane, driving it through the Terminal app's UI via `adb input` is not
viable as an ongoing interface — it only worked at all because a human was
present to tap Enter physically each time. Real SSH access is a
requirement, not a nice-to-have, for Debian to be usable headlessly.

## Stage 2B — SSH inside the guest: installed and running, not yet reachable

Using the fragile flow above (bootstrap only), confirmed live:

- **Passwordless sudo** for the `droid` user (`sudo -n true` returns
  cleanly, no password prompt) — genuinely confirmed this time; an earlier
  apparent confirmation was a false read caused by the same `&&`
  word-splitting bug (it was Android's own shell echoing an unrelated exit
  code, not anything from inside Debian).
- **`apt` fully functional**, real internet access: `apt update` fetched
  27.8 MB from deb.debian.org at ~7.7 MB/s. Debian 13 "trixie".
- **`openssh-server` installed cleanly** via apt, with genuine systemd
  integration: real unit symlinks created
  (`/etc/systemd/system/multi-user.target.wants/ssh.service`), SSH host
  keys generated (RSA/ECDSA/ED25519), `systemctl status ssh` reports
  `Active: active (running)`, PID tracked, proper `CGroup`. This is real
  systemd, not a minimal/fake init — confirms one of Stage 2's original
  open questions outright.
- **Guest networking is a private NAT, not LAN-bridged**: `ip addr` shows
  `enp0s12` at `10.70.217.197/24`; `ip route` shows the default gateway at
  `10.70.217.78` on the same interface — completely separate address space
  from the Android host's LAN IP (`192.168.68.60`). The Android host itself
  *can* reach the guest directly (`nc -z 10.70.217.197 22` from the host
  succeeds), confirming the NAT path exists — but nothing on the Mac/LAN
  side can reach it without something bridging that gap.

### Port-forwarding attempt: first try failed, root cause found

Found the actual control (Terminal app → Settings → Security → **Port
control → "Auto-forward all ports"**, off by default, "may pose security
risks" warning). Enabled it, then restarted `ssh.service` inside the guest
to force a fresh bind/announcement. Result: **no change** —
`nc -zv 192.168.68.60 22` from the Mac still gets `Connection refused`, and
scanning the Android host's own `/proc/net/tcp`/`tcp6` before and after
shows no new listener at all (the only new-looking entry, a loopback-only
port owned by the Terminal app's own UID, is almost certainly its internal
WebView-to-VM control channel, not anything SSH-related).

Root cause found (not by more guessing — by reading the actual AOSP
`forwarder_host` source): it **only forwards ports ≥ 1024, and only binds
`127.0.0.1`/`::1` on the Android host** — by design, not a bug or a
VM-restart timing issue. Port 22 was never going to appear no matter what
was toggled or restarted. This also explains why nothing showed up in
`/proc/net/tcp` scoped to port 22 specifically, and why the earlier "no
change" result wasn't a dead end, just a wrong assumption about which port
to look for.

## Stage 2B (resolved) — full headless SSH, proven live (2026-09-16)

Fix: moved guest `sshd` to port `2222` (via `/etc/ssh/sshd_config.d/20-overmind.conf`,
`Port 2222`), validated with `sudo sshd -t`, restarted. `ss -ltnp` confirmed
`LISTEN 0.0.0.0:2222` and `[::]:2222` inside the guest. The Terminal app's
own **Settings → Security → Listening ports** picked it up automatically as
soon as it started listening — `sshd (2222)` appeared there, pre-approved
(since "Auto-forward all ports" was already on).

Chain proven end to end from the Mac:

```text
Mac localhost:2222 → adb forward → Android localhost:2222
    → AVF/vsock forwarder → Debian VM:2222 → sshd
```

```bash
adb forward tcp:2222 tcp:2222
ssh -p 2222 droid@127.0.0.1
```

**Scoped down afterward (2026-09-16)**: `Auto-forward all ports` was only
useful diagnostically, to confirm the mechanism and find the ≥1024
restriction above. Once understood, least privilege says only the port
actually in use should be approved — turned back **off**, with `sshd
(2222)` left individually approved in the "Listening ports" list (that
per-port approval is independent of the master toggle and survives
turning it off, confirmed by testing — `ssh cerebrate-pixel6` still works
with the toggle off). Also cleaned up a stale `unknown (9999)` entry under
"Saved allowed ports" — a leftover from the local-forwarding negative test
in the reverse-tunnel security verification below.

Added the same forwarded SSH key already trusted on Overmind/Cerebrate to
`~/.ssh/authorized_keys` in the guest (bootstrapped through the fragile
`adb input` flow below, one time only — never needed again after this).
Real remote command execution confirmed:

```text
$ ssh -p 2222 droid@127.0.0.1 'hostname; whoami; uname -a'
debian
droid
Linux debian 6.12.92-android16-6-g4e585dd7f3b7-ab16266940-4k #1 SMP PREEMPT ... aarch64 GNU/Linux
```

Notable: the guest kernel is an **Android-branded build**
(`6.12.92-android16-...`), not a generic Debian kernel — best described as
a Google Android Common Kernel-derived guest kernel built specifically for
AVF, not the same kernel/tree instance as the Android host's own running
kernel. It remains a genuinely separate VM kernel; "Android-branded" here
is about provenance/build lineage, not a claim that host and guest share
a live kernel instance. Minor cosmetic issue, not yet fixed: `LC_ALL:
en_US.UTF-8` locale warning on every login (`apt install locales` should
resolve it, low priority).

**Open question for later, not blocking**: `adb forward` requires an active
USB/wireless-adb connection from a specific client (in this case, my Mac)
— it is not itself a persistent, any-LAN-device-reachable SSH path. Getting
genuinely LAN-wide SSH (any device on `192.168.68.0/22` connecting to
`cerebrate-pixel6.home.arpa:2222` directly, no adb involved) is a distinct
follow-up problem, since the AOSP forwarder is loopback-only by design.
Worth its own investigation before Stage 4, but doesn't block using SSH
*from this Mac* for everything from here on.

## VM-level "Keep awake" setting — set to 1 day (2026-09-16)

Terminal app → Settings → Advanced has its own **"Keep awake"** setting,
separate from Android's `stay_on_while_plugged_in` (which governs the
Android host, not the VM) — found **Off** at baseline, now set to **1 day**.
Also visible in the same screen: VM is allocated **1.0 GB RAM** out of the
host's 7.8 GB total.

Real finding: this is a **timed duration picker** (1 minute up to 1 day),
not a persistent on/off toggle — there's no "always" option. The dialog
itself warns "Enabling keep awake will significantly impact battery life
as it prevents the device from sleeping," which is expected/accepted for
an always-charging appliance, but the *timed* nature matters: **this
setting will need to be re-applied roughly daily**, or its actual renewal
behavior (does interacting with the terminal reset the countdown? does it
require manually reopening this dialog?) needs to be verified over a real
multi-day observation before assuming this alone solves Stage 1's
always-on requirement. Worth an explicit check before Stage 4's
sustained-workload testing.

## LAN-independent access — reverse SSH tunnel through Overmind (2026-09-16, done)

Resolved the "not yet solved" item above. Three architectures were
considered (an Android-side TCP relay via Termux/socat was ruled out
specifically because it would mean installing Termux *just to make Debian
reachable*, undermining the reason for using Debian at all); the chosen
one is a reverse tunnel the guest initiates outbound, landing on Overmind
— consistent with the project's existing preference to concentrate
Tailscale/remote-access surface on a couple of entry points rather than
enrolling every device:

```text
Mac → (LAN or Tailscale) → Overmind:2206 → reverse SSH tunnel → Debian:2222 → sshd
```

The credential shape follows this repo's existing rule from
[security-model.md](security-model.md#git-credentials) verbatim: **every
agent/process gets its own scoped credential, never a shared or personal
key.** Applied here as a genuine second example of that pattern beyond git:

- **Dedicated `pixel-tunnel` system account on Overmind** — `/usr/sbin/nologin`
  shell, no password, exists for exactly one purpose.
- **Fresh ed25519 key generated on the guest itself**
  (`~/.ssh/pixel-tunnel`, no passphrase — reasonable for an unattended
  service credential whose authority is tightly restricted server-side,
  not by secrecy of the passphrase). Never touches Overmind or the Mac.
- **Defense in depth on the server side**, both at the account level
  (`sshd_config` `Match User pixel-tunnel` block) and the individual key
  (`authorized_keys` options) — deliberately redundant:
  - `Match User pixel-tunnel`: `AllowTcpForwarding remote` (not `all` —
    local (`-L`) forwards stay blocked even if the key options ever
    drifted), `PermitListen 127.0.0.1:2206`, `GatewayPorts no`, plus
    `PermitTTY no`, `X11Forwarding no`, `AllowAgentForwarding no`,
    `AllowStreamLocalForwarding no`, `PermitTunnel no`, `PermitUserRC no`,
    `PasswordAuthentication no`, `KbdInteractiveAuthentication no`.
  - `authorized_keys`: `restrict,port-forwarding,permitlisten="127.0.0.1:2206",from="192.168.68.60"`
    — `restrict` disables everything by default (forwarding, PTY,
    agent/X11, user RC), `port-forwarding` selectively re-enables just
    forwarding, `permitlisten` pins the one allowed `-R` target,
    `from=` pins the source IP to the Pixel's actual LAN address
    (confirmed via `ss -tn` on Overmind showing the live connection's
    real remote address before applying the restriction — not assumed).
- **Pinned host key**: the guest's tunnel connects with
  `StrictHostKeyChecking=yes` against a dedicated
  `~/.ssh/known_hosts.overmind` containing Overmind's real host keys
  (fetched directly from `/etc/ssh/ssh_host_*_key.pub` on Overmind), not
  opportunistic TOFU acceptance.
- **systemd unit** (`/etc/systemd/system/pixel-tunnel.service` on the
  guest, running as `droid`): `Restart=always`, and
  `ServerAliveInterval=30`/`ServerAliveCountMax=3` instead of `autossh` —
  plain OpenSSH options are sufficient for detecting a dead connection and
  exiting so systemd restarts it. `ExitOnForwardFailure=yes` matters
  specifically: if `2206` were ever occupied or the forward refused, ssh
  exits immediately rather than sitting there looking healthy with a
  broken tunnel.

**Explicit invocation detail that matters**: the `-R` target must be the
literal `127.0.0.1:2206:127.0.0.1:2222`, not `localhost` — OpenSSH's
`PermitListen` matching distinguishes the literal address from the
hostname.

### Verified, not assumed

- Positive path: `ssh -p 2206 droid@127.0.0.1` from Overmind reaches the
  guest (`hostname` → `debian`) — full chain works.
- Negative path 1 (no shell): connecting as `pixel-tunnel` with a command
  returns `This account is currently not available.` (the standard
  `nologin` rejection).
- Negative path 2 (no local forwarding), done carefully: an `nc -z` probe
  against a `-L`-forwarded local port succeeding is **not** proof the
  server allowed it — the SSH client opens that local listener
  unconditionally regardless of server-side authorization; only a real
  data-carrying attempt exercises the server's decision. Redid the test
  reading actual bytes through the forwarded port:
  `channel 1: open failed: administratively prohibited: open failed` —
  the server genuinely rejects local forwarding, confirming
  `AllowTcpForwarding remote` (not `all`) is doing real work, not just
  present in the config.

### Known residual limitation (documented, not solved)

Overmind can restrict *where the reverse tunnel listens* (`127.0.0.1:2206`)
but cannot enforce *what the client dials on the far end* — the guest-side
`-R ...:127.0.0.1:2222` destination is a client-side decision Overmind has
no visibility into. The practical blast radius of a stolen guest key stays
very small regardless: it can establish exactly one loopback-only listener
on Overmind, get no shell, create no other listeners, and reach nothing on
the LAN directly — but this is a real, worth-remembering asymmetry between
"what the server can prove" and "what the client claims," not a solved
problem.

### DNS node entry + `ssh cerebrate-pixel6` alias — done (2026-09-16)

Two distinct, complementary pieces, not one:

1. **`cerebrate-pixel6.home.arpa` → `192.168.68.60`** added as a real node
   record in `hosts/dns-rewrites.yaml` (confirmed by the user as an actual
   DHCP reservation, not just a stable-looking lease — though it'll need
   updating here once this host moves to a planned wired connection).
   Matches the same node/alias/service convention already established for
   `cerebrate-pi0`/`overmind-01`. Useful for reachability, wireless-adb,
   and any future direct-to-Pixel service — but **this DNS name is not
   how SSH to the Debian guest works**, for a specific reason worth
   remembering: the tunnel's listener on Overmind is deliberately
   `127.0.0.1`-only (`GatewayPorts no`), so nothing on the LAN — including
   this new DNS name — can reach port `2206` directly. SSH still has to
   go *through* Overmind.
2. **Mac `~/.ssh/config`** — added a `Host cerebrate-pixel6` block using
   `ProxyJump overmind-01` to reach `127.0.0.1:2206`, so `ssh
   cerebrate-pixel6` transparently does the full jump. Host keys pinned
   (not `StrictHostKeyChecking=no`) — fetched via `ssh-keyscan` through
   the already-trusted tunnel path, then **cross-checked against the
   guest's actual `/etc/ssh/ssh_host_ed25519_key.pub` fetched over the
   direct `adb forward` path** before trusting it, catching that an
   earlier manual transcription of the same fingerprint (read off a
   screenshot during the openssh-server install) had an O/0 ambiguity —
   the two independent fetches matched exactly once compared byte-for-byte
   rather than eyeballed.

Verified: `ssh cerebrate-pixel6 'hostname; whoami; uptime'` from the Mac
works end to end with no `adb` involved at all.

**Cross-reference — the wired-Ethernet migration has *two* dependencies on
this IP, not one.** The DNS record above is the obvious one. The less
obvious one: the reverse-tunnel key's `authorized_keys` restriction on
Overmind is pinned with `from="192.168.68.60"` (see the reverse-tunnel
section above). If this host's wired reservation gets a *different*
address than its current Wi-Fi one, the tunnel will fail authentication
— silently, from the guest's perspective, since the key itself is still
valid, just no longer presented from an allowed source IP — until both
the DNS record **and** that `from=` restriction are updated together.
Treat these as one change, not two independent ones, whenever this host's
IP changes for any reason.

## Stage 3 — control-plane decision and validation (2026-09-16)

Expanded beyond the original one-line judgment call into four bounded
validation passes, per an explicit request to look up documentation rather
than trial-and-error where possible. Findings below combine authoritative
sources (AOSP docs, crosvm docs, the GrapheneOS AVF deepwiki) with direct
empirical testing on this actual device — documentation alone was
incomplete on several of these questions, so both were used and each
finding below is labeled as one or the other.

### 1. Unattended lifecycle behavior

**Documented (before testing):**
- The VM runs under `VmLauncherService`, a genuine Android foreground
  service, not a plain background process — more resistant to the Low
  Memory Killer than an ordinary app. [Source: GrapheneOS AVF deepwiki]
- crosvm/AVF supports `virtio-balloon`, integrated with the Android app
  lifecycle specifically to reclaim guest memory when the host app is
  backgrounded, avoiding LMK. [Source: AOSP virtualization architecture
  docs, crosvm balloon docs]
- Independent reporting (predating this session, describing early
  rollout behavior) claimed the VM closes when the Terminal app is
  exited and can still be LMK-killed — the community workaround is a
  root-requiring Magisk module, which this project deliberately avoids
  (rooting is off the table per this doc's own stated constraint).
  [Source: community blog/forum posts, not authoritative AOSP docs —
  flagged as lower-confidence going into testing]
- Android file-based encryption (FBE) makes Credential-Encrypted (CE)
  storage — the default for regular apps — unavailable until the user's
  first unlock after boot; Device-Encrypted (DE) storage is the only
  thing available pre-unlock, and is reserved for a small set of system
  apps. The Terminal app's VM disk images live under `/data/media`; the
  general default (CE) would mean the VM's own storage is inaccessible
  until first unlock, though this session found no source stating that
  *specifically* for this app rather than as a general Android default.
  [Source: AOSP file-based-encryption docs]

**Empirically tested on this device (2026-09-16), each verified by
actually breaking or recovering the connection, not assumed:**

| Scenario | Result |
| --- | --- |
| Screen off + idle, 90s | **Survives.** Guest/SSH fully responsive throughout. |
| Terminal app backgrounded (confirmed via `dumpsys activity` showing the launcher as resumed, not the Terminal app) + screen off, 4 min | **Survives.** Continuous uptime, no VM restart. |
| Terminal app force-stopped (`am force-stop`) | **Guest dies immediately.** `vm list` goes empty; confirms the community reports were correct for this exact action on this device, regardless of the foreground-service architecture. |
| Recovery: relaunch the Terminal app after a force-stop | **Fully automatic** — VM boots fresh (new CID), and both `sshd` and `pixel-tunnel.service` auto-start via their own `systemctl enable` with zero manual reconfiguration. Recovery is "reopen the app," not a reprovision. |
| Wi-Fi disabled then re-enabled | **Survives, self-heals, but not instantly.** The guest itself stayed reachable throughout via the USB/`adb forward` path (unaffected by Wi-Fi). The reverse tunnel failed to reconnect for ~30-60s after Wi-Fi returned (`remote port forwarding failed for listen port 2206`) — a stale, abruptly-dropped TCP connection lingered on Overmind's sshd until its own keepalive/timeout noticed and freed the port; `Restart=always` kept retrying every 5s until it succeeded on its own, no intervention needed. |

**Not yet tested — needs coordination, not solvable unilaterally:**
- **Full Android/Pixel reboot.** This is the single most important
  remaining lifecycle question (per the original request) precisely
  because FBE's first-unlock requirement means it almost certainly
  can't be fully automatic: even if `adb` reconnects over USB
  post-reboot, the VM's disk likely can't start until a human unlocks
  the screen, and the Terminal app itself would then need relaunching
  (per the force-stop test above, nothing suggests it auto-launches on
  boot). Testing this requires the user physically present to unlock
  the device afterward — cannot be done unilaterally.
- **Overmind unavailable/restarted.** Deferred deliberately: testing
  this properly means restarting `ssh.service` (or the whole host) on
  Overmind, which is a real, in-use production media server, not a test
  sandbox — not something to do casually mid-experiment without explicit
  go-ahead, unlike the Pixel-side tests above which only risked this
  one experimental node.

### 2. This Debian guest vs. stock Debian — the compatibility boundary

**Ordinary Debian, unmodified, above this line:**
- Release: Debian GNU/Linux 13 "trixie" (13.6), completely standard
  `/etc/os-release`.
- Package management: real `apt`, real `dpkg`; grepping installed
  packages for anything Google/AVF-branded turned up nothing (the two
  false-positive hits were `libavfilter`/`libavformat` — FFmpeg
  libraries, matched only because "avf" is a substring of "libavfilter").
  **The userspace/package layer is entirely vanilla Debian — no
  guest-side agent or special AVF package exists.**
- systemd, `/etc/ssh`, standard service management — all behave exactly
  like a normal Debian system, as already established in Stage 2.

**Android/AVF-specific, below this line:**
- **apt sources point at a local mirror redirector**
  (`mirror+file:///etc/apt/mirrors/debian.list`) rather than a hardcoded
  `deb.debian.org` URL — the one deviation at the package-management
  layer, presumably for reliability/mirror-selection, not a security or
  compatibility concern.
- **Kernel is Android-branded and monolithic**: `6.12.92-android16-...`,
  built by Google's `kleaf` build system with Clang/LLD/PGO/BOLT/MLGO —
  and `lsmod` reports zero loaded modules. Everything is compiled
  directly into the kernel image; there is no dynamic module loading in
  use at all, unlike a typical Debian kernel.
- **15 virtio devices** (decoded against the standard virtio spec device-ID
  table): GPU (id 16), 3× console (id 3), 2× block (id 2, matching
  `/dev/vda` root disk + `/dev/vdb` a read-only ISO9660 seed volume
  mounted at `/var/lib/cloud/seed/nocloud` — cloud-init-style guest
  provisioning), rng (id 4), 4× input (id 18), network (id 1), vsock
  (id 19), and one more (id 26) not confidently identified against the
  common device-ID list.
- **`/dev/vsock` and `/dev/vhost-vsock`** — real vsock support, matching
  the `cid: 2048`/`2049` seen in `vm list` across VM instances.
- **`/mnt/shared` → `android` via `virtiofs`** (autofs-triggered) — a
  genuine host↔guest shared-folder bridge; contents are permission-gated
  (couldn't browse `/mnt/shared/Android` as `droid`).
- **`/sys/class/android_usb`** — an Android-specific sysfs class exposed
  straight into the guest, something that would never exist on bare-metal
  or conventional-hypervisor Debian.
- **A second block device mounted read-only as an ISO9660 "nocloud" seed**
  — cloud-init's standard mechanism for injecting per-instance config,
  confirms the guest is provisioned cloud-init-style at boot, not via a
  custom Google-authored first-boot script.

### 3. GPU/DRM/accelerator visibility

- `/dev/dri/card0` and `/dev/dri/renderD128` **do exist**, and
  Mesa/Vulkan userspace (`mesa-vulkan-drivers`, `libvulkan1`,
  `vulkan-tools`, `libgl1-mesa-dri`) is pre-installed — nothing had to be
  added to check this.
- `vulkaninfo --summary` gives a definitive, unambiguous answer:
  `deviceName = llvmpipe`, `driverID = DRIVER_ID_MESA_LLVMPIPE`. This is
  Mesa's pure-**software** CPU rasterizer, not real hardware.
- Matches a documented, dated fact found via search: gfxstream-based real
  GPU passthrough for the Terminal app was reported as a **Pixel 10-only**
  rollout with major limitations even there (only 47 of 142 Vulkan
  extensions exposed, some non-functional). This is a Pixel 6 — predates
  that rollout entirely.
- **No TPU/EdgeTPU/NPU device nodes of any kind** found in the guest
  (`find /dev /sys -iname '*tpu*' -o -iname '*edgetpu*' -o -iname
  '*npu*'` turned up nothing related). Confirms the Tensor chip's NPU is
  never exposed to Debian, matching the intended architecture split.

**Classification: effectively CPU-only** (option 3 of the three offered).
A `/dev/dri` node existing is not the same as acceleration existing —
worth remembering if this gets re-checked after a future OS update, since
the device node alone would look identical either way; the driver
actually in use is what settles it.

### 4. Real memory budget

| Where | Value |
| --- | --- |
| Guest `MemTotal` | 982,680 kB (≈960 MiB) — close to, not exactly, the configured "1.0 GB" |
| Guest `MemAvailable` (idle, one login) | ≈604 MB |
| Guest swap | `zram0`, ≈480 MB, compressed-RAM-backed — **not** real additional capacity for incompressible data (model weights, tensors); helps with generally-compressible pages, not a reliable extension of the practical ceiling for ML workloads specifically |
| Guest cgroup limits | cgroup v2 mounted; no `systemd` `MemoryMax` set at any slice — the VM's own RAM allocation is the only real ceiling |
| Balloon driver | Present (`virtio_balloon` bound), confirming the documented Android-lifecycle-integrated reclaim mechanism exists on this build |
| Android host `MemTotal` | 7,787,844 kB (≈7.8 GB) |
| Android host `MemAvailable` (with guest running, one SSH session) | ≈2.95 GB |

**Practical ceiling for Debian workloads**: roughly 900 MB of real RAM
plus a compressible-only zram swap cushion — meaningfully less than the
Pixel's advertised 8 GB, and the zram distinction matters specifically
because a future inference workload's memory pressure (model weights)
is exactly the kind of data zram compresses poorly. **Do not plan Stage
4's workload sizing against the 8 GB host figure or the round "1 GB"
VM config number — use the ≈900 MB/600 MB-available guest figures.**
Android-native inference separately has roughly 3 GB "available" to work
with under current conditions, though that number will shrink under
real load from other host-side apps/services.

## Stage 3 decision

**Adopt Debian as the control plane, with two carried-forward caveats.**

The decision rests on lifecycle reliability, normal Linux administration
behavior, and usable resource limits — not on accelerator access, which
was never expected to exist here and doesn't count against this decision
per the original framing.

- **Debian**: SSH, systemd, orchestration, Python/native utilities,
  preprocessing, queues, model/artifact management, APIs, monitoring —
  everything checked in Stages 2-3 supports this being genuinely reliable
  for that role.
- **Android**: hardware-facing inference and anything requiring the
  Pixel's GPU/Tensor/EdgeTPU/Android ML APIs — confirmed necessary, since
  Debian has zero visibility into any of that hardware.

### Unresolved risks/constraints carried into Stage 4

1. **The Terminal app must never be force-stopped or fully closed** while
   this node is meant to be "up" — this is now a confirmed, not
   theoretical, single point of failure for the whole control plane.
   Nothing currently prevents Android itself, a future OS update, or an
   accidental user action from doing exactly that. Worth a periodic
   external health check (e.g., from Overmind, "is `2206` still
   listening") rather than assuming it stays up indefinitely.
   **Materially de-risked as of 2026-09-16**: this exact failure happened
   for real (unplugging the Pixel from USB to move it to AC power closed
   the Terminal app and killed the VM — the human-triggered version of the
   same failure mode proven in Stage 3), and recovery turned out to need
   **no physical presence at all**. Overmind already has its own
   independent wireless-ADB pairing with the Pixel
   (`adb -s 192.168.68.60:5555`, over the LAN, separate from any USB
   tether to a Mac) — `adb shell am start -n
   com.android.virtualization.terminal/.new2.ui.MainActivity` through that
   connection relaunched the app remotely, the VM booted fresh, and
   `sshd`/`pixel-tunnel.service` both auto-started exactly as Stage 3
   found. Verified end to end from **off the home LAN, over Tailscale**
   — full chain: Mac → Tailscale → Overmind → `adb` (wireless, LAN-local
   to Overmind) → relaunch, then Mac → Tailscale → Overmind → reverse
   tunnel → guest, confirming the recovery path doesn't require being on
   the home network either. This turns risk #1 from "nothing prevents
   this and recovery needs someone at the device" into "this can happen,
   and recovery is one remote command away, from anywhere." The
   periodic-health-check idea above is still worth doing (to know
   *quickly* rather than by accident, as this instance was discovered),
   but the severity of this risk is now much lower than originally
   assessed.
2. **Full-reboot recovery is unverified and, per FBE, likely not fully
   automatic** — probably requires a human to unlock the screen and
   relaunch the Terminal app after any reboot. This needs to be tested
   deliberately (with the user present) before this node can be trusted
   as truly unattended across, say, a power outage.
3. **Reconnection after a network interruption takes up to ~60s**, not
   instant, due to stale-socket cleanup on Overmind's side — fine for an
   inference node, but worth knowing before building anything with a
   tighter reconnection-time expectation on top of this tunnel.
4. **Real usable RAM is ≈900 MB, with a compression-only swap cushion** —
   Stage 4's workload must be sized against this, not the Pixel's
   advertised 8 GB or the round "1 GB" VM config number.
5. **The VM-level "Keep awake" setting (Stage 2) is time-limited (1 day
   max, not permanent)** and its actual renewal behavior over multiple
   days is still unverified — a real risk of the guest eventually
   sleeping again despite today's setting, independent of everything
   tested in this pass.
6. **"Overmind unavailable/restarted" reconnection is untested** —
   deliberately deferred rather than disrupting the production media
   server; should be tested once there's a legitimate reason to restart
   Overmind's `ssh.service` anyway, not as a standalone disruptive test.

Stage 4 (minimal inference service + thermal/power characterization) is
explicitly not started as part of this pass.

## Stage 4 — first vertical slice: accelerated inference proven (2026-09-16)

Goal: prove the complete loop `Debian → Android-native service →
accelerated inference on Pixel hardware → result → Debian`, deliberately
tiny — one small known-good model, one input shape, no scheduler/queue/
orchestration — while collecting thermal, memory, and latency data.
Debian-control-plane / Android-native-inference is the architecture this
tests, per the Stage 3 decision; no infrastructure optimization first.

### The biggest open question, resolved immediately

Whether NNAPI (and therefore real hardware acceleration) is even reachable
from a plain pushed executable — not an installed, Play-Store-verified
app — was unknown going in. Tested directly with Google's official
prebuilt `benchmark_model` tool (`android_aarch64_benchmark_model`,
pushed via `adb push` + `chmod +x`, run via `adb shell`, no install step
at all):

```text
NNAPI accelerators available: [google-edgetpu,nnapi-reference]
Explicitly applied NNAPI delegate, and the model graph will be
completely executed by the delegate.
Inference (avg): 766 microseconds
```

**Real, named hardware acceleration (`google-edgetpu`) is reachable from a
plain shell-executed process.** Confirmed further by explicitly forcing
`--nnapi_accelerator_name=google-edgetpu` rather than trusting
auto-selection — identical ~776µs average, proving auto-selection was
already correctly choosing the accelerator, not silently falling back to
CPU or the `nnapi-reference` software path. (Separately, attempting the
APK-wrapped variant of the same tool hit
`INSTALL_FAILED_VERIFICATION_FAILURE` from Play Protect — expected on a
no-Google-account device with a sideloaded, unrecognized APK. Abandoned in
favor of the native binary, which is also the more representative choice:
the eventual real service is a background process, not an installed app.)

Model used: `mobilenet_v1_1.0_224_quant.tflite` (official Google-hosted
quantized MobileNetV1) — small, standard, known-good, no custom training
or conversion needed.

### The minimal bridge (deliberately not production code)

Debian can reach the Android host directly over the guest's own NAT
gateway address (`10.70.217.78`, confirmed with a plain `nc` reachability
test before building anything) — no vsock code, no `adb forward` needed
for this direction. That made the simplest possible bridge a shell script,
not a real server:

```sh
# /data/local/tmp/inference-server.sh, run via `adb shell` (kept alive as
# a background task — a job backgrounded with `&` inside a transient adb
# shell invocation dies when that invocation ends; this bit twice today)
while true; do
  BENCH=$(benchmark_model --graph=... --use_nnapi=true \
    --nnapi_accelerator_name=google-edgetpu --num_runs=30 ...)
  # bundle in a live TPU thermal reading, battery temp, host meminfo
  { echo "BENCH|$BENCH"; echo "TPU|..."; echo "BATT|..."; echo "HOSTMEM|..."; } > resp.tmp
  nc -l -p 8765 < resp.tmp
done
```

Debian drives it with a plain `nc 10.70.217.78 8765` loop, logging
round-trip time and parsing out the bundled metrics per request.

**Two real bugs hit and fixed, both worth keeping as lessons:**
1. Backgrounding the server loop with `adb shell 'cmd &'` doesn't survive
   — the child dies when that specific `adb shell` invocation's connection
   ends. Fix: run `adb shell 'sh server.sh'` itself as a kept-alive
   background task (same lesson as the reverse-tunnel work earlier this
   session, re-learned here in a new context).
2. `{ ... } | nc -l -p PORT` (piping straight into `nc -l`) races —
   roughly 1 in 3 requests got an accepted-but-empty response, worse once
   requests came back-to-back (a consistent every-other-request failure
   pattern once retries were added, implying the server's real cycle time
   didn't match the client's retry cadence). Root cause not fully
   chased down (toybox `nc`'s rapid listen/accept/close cycling is the
   suspect); pragmatically fixed two ways rather than one: (a) write the
   full response to a file before starting `nc -l`, removing the pipe
   timing race, and (b) make the Debian-side client retry-on-empty with a
   wide enough window (15 attempts, 0.5s apart) to reliably catch the
   server's actual ~2.6s cycle time. **This flakiness is a property of the
   deliberately-minimal `nc`-based bridge, not of NNAPI/inference itself**
   — worth a real HTTP/socket server (Python or a small native binary) if
   this bridge needs to survive past this one experiment.

### Sustained-load results: 40 clean requests

| Metric | Result |
| --- | --- |
| Inference latency (pure, reported by `benchmark_model`) | Mean 777.4µs, range 765.8-787.9µs — **flat across all 40 requests, no degradation under sustained load** |
| TPU thermal (dedicated sensor from Stage 1) | Climbed from 41°C to a 50-52°C plateau over the run — a real, bounded ramp approaching steady-state, not runaway |
| Battery temp (general sensor) | 26.3°C → 27.2°C — much smaller movement than the TPU-specific sensor, confirming Stage 1's finding that the dedicated TPU sensor is the meaningfully more sensitive instrument for this kind of work |
| Android host `MemAvailable` | Stable ~3.23-3.24 GB throughout — no leak from 40 repeated process spawns |
| Debian `MemAvailable` | Stable ~624-629 MB throughout — no leak on the client side either |
| Round-trip time (client-observed) | **Not a meaningful latency number** — dominated by the `nc` bridge's retry-polling overhead (~2.6s mean) and each request's fresh-process `benchmark_model` init cost (~800ms), neither of which reflects a real service's latency. The 777µs figure above is the actual finding; the RTT is an artifact of this session's deliberately-thrown-together bridge. |

### What this proves, and what it doesn't yet

**Proven**: the full architecture works — Debian can trigger real,
confirmed hardware-accelerated inference on the Pixel's EdgeTPU and get a
result back, with no installed app, no root, and no fragile UI-driven
workaround anywhere in the loop. Thermal behavior is genuinely measurable
and well-behaved at this load level. Neither side leaks memory under
repeated requests.

**Not yet tested** (explicitly out of scope for this deliberately tiny
first pass, carried into a follow-up):
- Longer sustained runs to find whether/when thermal throttling actually
  onsets (this run's 50-52°C plateau may just be this load level's
  steady-state, not a throttling ceiling — `dumpsys thermalservice`'s
  `Thermal Status` field, `0`/nominal in every prior check, is the signal
  to watch for a real transition).
- A real model larger than MobileNetV1-sized, more representative of
  actual intended workloads.
- A real server (not the `nc` shell-loop bridge) — needed before this
  becomes anything other than a proof.
- Concurrent/overlapping requests rather than strictly serial one-at-a-time.
- Behavior across one of Stage 3's unresolved lifecycle risks (e.g., does
  a sustained inference load change anything about the force-stop/Wi-Fi/
  reboot findings from Stage 3 — untested combination).

## Backend decision: LiteRT v2 spike vs. legacy NNAPI (2026-09-16)

Before building the persistent worker, tested Google's supported successor
API (LiteRT v2 `CompiledModel`, prebuilt `libLiteRt.so` pulled from Maven
per the same AAR-extraction approach used elsewhere in this session, no
Bazel build) against the same MobileNetV1 model, on the same hardware, all
three accelerator paths:

| Path | Mean latency | vs. `google-edgetpu` |
| --- | --- | --- |
| NNAPI → `google-edgetpu` (established baseline) | 777 µs | — |
| LiteRT v2 → GPU (OpenCL) | 10,368 µs | ~13.3× slower |
| LiteRT v2 → CPU (XNNPACK) | 33,528 µs | ~43× slower |
| LiteRT v2 → NPU | did not load | `NPU accelerator could not be loaded and registered: kLiteRtStatusErrorInvalidArgument` — confirms live, on this exact device, that Tensor NPU support isn't available through the modern stack yet (matches Google's documented Tensor-G5-only NPU support, but observed directly rather than only read) |

**Caveat**: the GPU run also logged `Failed to get buffer requirements for
tensor 'input'`, suggesting a possible non-zero-copy fallback path — true
best-case GPU performance might be somewhat better than measured. Not
enough to plausibly close a 13× gap.

**Conclusion**: Pixel 6 backend = legacy TFLite + NNAPI →
`google-edgetpu`. The architecture stays backend-neutral regardless (see
`cerebrate-infer` below) — NNAPI is a hardware-compatibility shim for this
specific first-generation Tensor chip, not an API exposed to callers of
the inference service. Nothing outside the one `NnapiTfliteEngine`
implementation needs to know NNAPI exists.

**Why this is acceptable, not just accumulating technical debt**: the
evidence is unusually decisive — all three modern-stack accelerator paths
were actually measured on this exact hardware (not assumed from
documentation), NPU unavailability was confirmed live, and the best
available modern path was still an order of magnitude slower than the
deprecated one. Migration trigger for revisiting this: re-evaluate LiteRT
NPU support on future Tensor-generation hardware, or when Google expands
supported Tensor generations beyond G5.

## Persistent worker: `cerebrate-infer` — built and working (2026-09-16)

First implementation kept deliberately narrow:

```text
cerebrate-infer
├── InferenceEngine (seam)
│   ├── NnapiTfliteEngine   ← implemented: load model once, create NNAPI
│   │                          delegate once, force google-edgetpu, Run()
│   └── LiteRtEngine        ← declared, not implemented — the seam is
│                              real without doubling this pass's scope
├── serialized request loop (one at a time, no concurrency)
├── TCP listener on the AVF-facing interface (0.0.0.0, not hardcoded to
│   today's 10.70.217.x — the address is AVF-managed and not assumed
│   stable across VM restarts, only the binding interface choice is fixed)
└── response: result, inference_us, backend="google-edgetpu"
```

### Getting a real binary linked against real TFLite+NNAPI code

Same AAR-extraction trick that worked for the LiteRT spike, applied to the
legacy TFLite Android AAR (`org.tensorflow:tensorflow-lite:2.16.1`, pulled
from Maven Central — 2.17.0 dropped native AAR publishing, 2.16.1 still has
one): extract `jni/arm64-v8a/libtensorflowlite_jni.so` plus the bundled
`headers/` tree. Confirmed via `llvm-nm -D` (NDK 27.1's toolchain) that the
exact needed symbols are exported before writing any code:
`TfLiteNnapiDelegateCreate`, `TfLiteNnapiDelegateOptionsDefault`,
`TfLiteNnapiDelegateDelete` — and the bundled
`nnapi_delegate_c_api.h` header confirms `accelerator_name` is a real
field on the C API struct, not something only reachable from the internal
C++ class. No Bazel build needed anywhere in this session.

Two small, quickly-resolved build issues (kept as lessons, not treated as
archaeology — per the explicit instruction to stop quickly if this
started dragging):
- Two headers genuinely missing from the AAR's bundled `headers/` tree
  (`tensorflow/lite/core/async/c/types.h`,
  `tensorflow/lite/core/c/registration_external.h`) — pulled directly from
  the matching `v2.16.1` tag on GitHub to keep ABI/version consistency,
  rather than the latest `master`.
- `nnapi_delegate_c_api.h` uses C++-only nested-enum syntax despite being
  wrapped in `extern "C"` — compiling the file as C++ (`.cc`, `clang++`)
  instead of C resolved this immediately, along with two trivial explicit
  casts C++ requires that C doesn't (`void*` → `unsigned char*`).
- Runtime link error `library "libc++_shared.so" not found` on first run
  — expected once compiling as C++; pushed it from the NDK sysroot
  alongside the binary.

### Verified working, with a real latency nuance worth keeping

```text
$ echo | nc 10.70.217.78 8765
request_id=1 top_class=795 top_score=120 inference_us=12071   (cold, after idle)
request_id=4 top_class=795 top_score=120 inference_us=1292    (warming up)
request_id=8 top_class=795 top_score=120 inference_us=1190    (steady-ish)
```

The resident worker is genuinely serving repeated requests without any
per-request process spawn (confirmed: no new process appears in `ps`
between requests, unlike the retired `nc`-bridge/`benchmark_model`
approach) — but an **isolated request after idle costs ~8-12ms**, dropping
to **~1.1-1.3ms with sustained back-to-back requests**, still somewhat
above the tight-loop `benchmark_model` figure of 777µs. Plausible
explanation, not yet confirmed: CPU/NPU clock scaling relaxes between
sparse requests (network round-trip + `accept()`/`read()` gaps between
calls), unlike `benchmark_model`'s internal loop with zero gap between
`Invoke()` calls. This is exactly the kind of real distinction Stage 4D's
proper sustained-load characterization (continuous load over
1/5/15/30-minute windows, not one-off pokes) needs to pin down — carried
forward as the first concrete question for that pass, not resolved here.

## Stage 4D — sustained-load characterization — CLOSED / PASS (2026-09-16)

### Saturation gates: 1 / 5 / 15 minutes

Single-connection, persistent-connection load client (bash-client overhead
was diagnosed and eliminated first — a bash generator spawning
`date`/`grep`/`cut` per request bottlenecked at 14.3 req/s, masking the
real hardware ceiling; a tiny Python socket client fixed this). Serialized
one-request-at-a-time throughput against real `google-edgetpu` NNAPI
inference settled at **~566-567 req/s**, with per-request
`inference_us` flat around **~1.1-1.3ms** — no latency drift, no
throughput decay, across all three gate durations. Worker RSS stayed
flat; no leak signal at this timescale.

### Memory-drift detour: isolated and closed

An early ~75MB `MemAvailable` decline seen during dense (~5-10s interval)
sampling triggered a dedicated isolation experiment (Control A:
sampler-only, no load; Test B: load with sparse sampling, later
invalidated by a spontaneous VM death and a client bug that lost all
data because it buffered rows in memory and only wrote the CSV at exit).
The two-hour moderate-load soak below settled this cleanly: with a
low-frequency instrumentation profile, host `MemAvailable` moved in a
**158MB band with no monotonic direction** over two hours. The earlier
decline is now attributed to the sampler's own polling overhead/frequency,
not a real leak in the worker or the inference stack — this is a
plausible-cause closure, not a proven mechanism, and is not being
pursued further.

### Crash-isolation: load intensity ruled out as a direct cause

Two spontaneous Debian-guest deaths occurred during earlier testing (one
from a physical USB disconnect closing the Terminal app — expected; one
genuinely spontaneous, with nobody touching the phone, uncovered while
investigating the memory-drift detour). Rather than assume LMK or guess,
a rigorous two-configuration comparison was run with external,
Overmind-side instrumentation independent of the guest: a durable,
per-request-flushed Python load client, a 5s-interval liveness heartbeat
sampling `vm list` / terminal PID / worker PID / host `MemAvailable` /
thermal state over ADB, capturing a full `dumpsys` diagnostic bundle
immediately on any `vm_running` true→false transition, plus continuous
`adb logcat` capture running throughout.

- **Test 1** — TPU load alone, driven from Overmind via
  `adb forward tcp:8765 tcp:8765` to loopback, Debian otherwise idle:
  69,931 requests / 420s / 166.5 req/s. 89/89 heartbeat samples
  `vm_running=1`, worker PID constant, TPU peaked 40°C then cooled to
  32°C. Survived cleanly.
- **Test 2** — TPU load + active Debian workload, load client running
  *inside* Debian over the real production path
  (`10.70.217.78:8765`, the AVF gateway, not the ADB/loopback lab path):
  235,842 requests / 420s / **561.5 req/s**. 87/87 heartbeat samples
  `vm_running=1`, terminal PID and worker PID both constant, thermal
  status nominal (0) throughout. Survived cleanly at over 3x Test 1's
  throughput.

Neither configuration reproduced the death in a 7-minute window. This
retires the simple hypothesis that sustained TPU load, or Debian-driven
network traffic, or the two combined, directly kill the VM. Test 2 is the
more persuasive of the two: it exercised the actual production-shaped
path (Debian → AVF gateway → Android host) at high throughput with the
guest fully active, and still didn't reproduce anything.

### Moderate-load appliance soak — the real Stage 4D question

A stress test doesn't describe how this node will actually be used.
`cerebrate-infer` is meant to be an always-available appliance backend,
not a benchmark target — so the decisive test is a realistic duty cycle,
not another saturation run. Ran a **120-minute soak at 15 req/s**
(within a chosen 10-20 req/s appliance-shaped range) from inside Debian
over the real production path, with deliberately lightweight
instrumentation this time: liveness poll every 45s (vm list / PIDs /
`MemAvailable`, cheap), a heavier thermal+battery `dumpsys` snapshot only
every 5 minutes, full diagnostic bundle reserved for an actual death
transition, plus the same continuous logcat capture running throughout.

Result: **108,001 requests, 0 errors, 15.00 req/s sustained for the full
7200s.**

| metric | value |
|---|---|
| `rtt_us` (client-observed) | mean 2160, p50 2073, p95 2664, p99 3336, max 14424 |
| `handle_us` / `inference_us` | mean ~1180, p50 ~1135, p95 ~1380, p99 ~1600, max ~8270 |
| liveness | 159/159 heartbeat samples `vm_running=1`; terminal PID (31406) and worker PID (28046) constant for the entire run |
| thermal status | 0 (nominal) throughout |
| TPU temp | 34.0°C → 36.0°C |
| battery temp | 28.0°C → 28.9°C |
| host `MemAvailable` | 3,464,892–3,622,852 KB (158MB band, no monotonic trend) |

No latency drift, no thermal concern, no leak signal, no crash, over a
duration an order of magnitude longer than any prior test.

### Two performance regimes worth keeping distinct

- **Saturation** (hardware ceiling): ~0.9-1.3ms typical inference,
  hundreds of req/s depending on client/connection path (up to 566-567
  req/s single-connection-serialized).
- **Realistic moderate service** (appliance-shaped): 15 req/s,
  ~1.18ms inference, ~2.16ms mean end-to-end RTT, thermally trivial.

The gap between these regimes is the headroom this node has for actual
production traffic.

### Stage 4D status: CLOSED / PASS

**Proven:**
- the persistent Android-native worker (`cerebrate-infer`) is stable
  under both saturation and realistic load
- real `google-edgetpu` NNAPI inference is stable, with no observed
  latency drift over a 2-hour run
- the full Debian → AVF gateway → Android host production path is
  stable under realistic load
- no worker or host memory leak observed once sampling overhead itself
  was controlled for
- moderate appliance-shaped load is thermally trivial on this hardware
- TPU load intensity — alone or combined with Debian-originated network
  traffic — is not sufficient to reproduce the spontaneous VM death

**Not claimed:** the precise mechanism behind the earlier ~75MB
sampling-era decline (attributed to sampler overhead, not proven), or
the cause of the spontaneous VM death (see below — deliberately kept
open as a separate track rather than holding Stage 4D for it).

### Separate lifecycle investigation — OPEN (not part of Stage 4D)

One spontaneous Debian VM death remains unexplained. Now excluded as a
direct/simple cause: high TPU utilization, Debian-originated request
load, moderate sustained appliance load, and simple elapsed time up to
two hours under active workload. Still plausible: long idle/background
lifetime beyond what's been tested, Terminal/Android foreground-service
lifecycle events, unrelated Android memory reclaim or scheduled OS
maintenance, an AVF/Terminal experimental-runtime bug, or interaction
with the "Keep awake" (1-day) timer expiring.

The most informative remaining experiment is elapsed time, not stress —
a long low/no-load idle-survival window. Rather than run that as a
dedicated blocking test, a passive, low-frequency liveness heartbeat
(60s liveness poll / 10-min thermal snapshot) and continuous `adb
logcat` capture are left running independently and indefinitely as a
longitudinal control-plane observation. If a death occurs, the
surrounding logcat and heartbeat evidence will already be captured, and
it becomes its own incident writeup rather than a reason to hold this
phase open.

One result from this investigation is worth preserving prominently: the
Android inference plane (`cerebrate-infer`) demonstrably survives
independently of the Debian guest's lifecycle — it kept running,
unaffected, straight through an earlier real VM death. That decouples
"is the Debian control plane reliable" from "is this node useful as an
inference appliance," and points toward a future health-manager design
where Debian is treated as a recoverable controller rather than a single
point of failure: inference worker stays up regardless → Overmind
detects control-plane/tunnel loss → Terminal VM relaunched remotely via
Overmind's independent wireless ADB pairing → systemd services and the
reverse SSH tunnel recover automatically (already demonstrated) →
control plane rejoins. Control-plane restartability, not perfect Debian
guest reliability, is the property this architecture actually needs.
