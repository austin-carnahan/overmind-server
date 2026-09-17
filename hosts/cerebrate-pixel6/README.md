bash: warning: setlocale: LC_ALL: cannot change locale (en_US.UTF-8): No such file or directory
# cerebrate-pixel6

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
Stages 1-3 done. **Decision: Debian is the control plane** (real
systemd/apt, three working SSH paths, GPU confirmed CPU-only/no NPU
visibility as expected). **Stage 4C done**:
[`cerebrate-infer`](cerebrate-infer/README.md), a persistent native worker,
loads the model + `google-edgetpu` NNAPI delegate once and serves repeated
requests from Debian — chosen over the newer LiteRT v2 API after directly
measuring it ~13× slower on this hardware. See the
[Pixel 6 inference node design notes](../../design-notes/2026-09-16-pixel6-inference-node.md)
for the full findings, including a confirmed single point of failure
(force-stopping the Terminal app kills the whole node) and other
carried-forward risks. **Stage 4D done**: sustained saturation, crash
isolation, and a 2-hour moderate-load appliance soak all closed out —
stable latency, no leak, no thermal concern, load intensity ruled out as
the direct cause of an earlier spontaneous VM death (that lifecycle
question stays open separately, under passive monitoring). **Stage 5
Phase 1 done**: [MLServer](mlserver/README.md) runs under systemd in the
Debian guest with a trivial echo model, ~120MB steady-state RSS,
verified health/readiness/inference endpoints and automatic restart
recovery. **Stage 5 Phase 2 done**: a thin custom runtime adapter wires
MLServer's V2 interface to `cerebrate-infer` over the real production
network path, verified end to end (correct classification output,
monotonic request-id continuity with earlier native tests, negligible
added memory). **Stage 5 Phase 3 done**: real image classification —
`cerebrate-infer`'s wire protocol now carries a real 224×224×3 input
tensor (no more fixed dummy pattern), and the MLServer adapter decodes,
resizes, and label-maps real images. Verified against the standard
Grace Hopper TensorFlow reference photo (correctly classifies
`"military uniform"` at 88.6% confidence, the well-documented expected
result for this model) and a content-sensitivity check (a flat-color
synthetic image yields a low-confidence, different label). **Stage 5
Phase 4 done**: `inference.home.arpa` reaches MLServer through Overmind
(Caddy → a small Docker-bridge `socat` relay → a loopback-only reverse
SSH tunnel, Debian-initiated, via a new narrowly-scoped
`pixel-mlserver-tunnel` credential mirroring the existing
`pixel-tunnel` pattern) — MLServer itself never listens beyond
loopback. Verified end to end including automatic recovery after a real
VM restart. That restart test also surfaced and fixed a genuine
pre-existing reliability bug in `cerebrate-infer` (a dead peer could
wedge the whole worker after a VM restart — see
[cerebrate-infer's README](cerebrate-infer/README.md)). One residual,
investigated-and-accepted looseness: `cerebrate-infer`'s own port stays
directly LAN-reachable (two narrower fixes were tested and ruled out
empirically); treated as consistent with this project's LAN/Tailscale
trust boundary, not a gap in it. Phase 5 (telemetry + reproducibility
close-out) not yet started.

A factory-reset Pixel 6, converted into a dedicated always-on inference node
for the home network. Second member of the "cerebrate" fleet/class (small
auxiliary compute nodes) — see the naming-convention section of the
[home DNS + reverse-proxy plan](../../design-notes/2026-09-15-home-dns-reverse-proxy-plan.md).
Stays a normal LAN device rather than joining Tailscale directly; remote
access is expected to come through Overmind/Cerebrate subnet routing, same
as everything else here.

| Item | Value |
| --- | --- |
| Machine | Pixel 6 (`oriole`, Tensor G1), 8-core CPU (arm64-v8a) |
| OS | Android 17 (SDK 37), build `CP3A.260905.009`, production (`ro.debuggable=0`) |
| RAM | 7.8 GB total |
| Storage | 110 GB `/data` (6.2 GB used at baseline) |
| Network interface | Wi-Fi (`wlan0`), DHCP-assigned `192.168.68.60/22`, WPA3-SAE, 5 GHz 802.11ax |
| Thermal sensors | Dedicated per-domain sensors incl. a distinct **TPU** sensor/cooling device — the Tensor NPU is thermally instrumented on its own, separate from CPU/GPU |

No SIM, no Google account, unnecessary radios/phone behavior minimized.
Developer Options + USB/Wireless ADB enabled. Android's experimental Debian
Linux guest is running (Debian 13 "trixie", real systemd, `openssh-server`
active on port `2222`) and reachable headlessly via `adb forward` — see the
design notes for the full chain and the AOSP forwarder's ≥1024/loopback-only
constraint that explains why.

## Access

- ADB over USB, currently authorized (`1A071FDF6007Q3`). Wireless ADB also
  enabled and persisted (`adb_wifi_enabled=1`).
- **Overmind also has its own independent wireless-ADB pairing**
  (`adb -s 192.168.68.60:5555`, over the LAN, not tied to any Mac's USB
  tether) — this is the important one operationally: it's what let the
  Terminal app get relaunched remotely (`adb shell am start -n
  com.android.virtualization.terminal/.new2.ui.MainActivity`) after it
  got closed by unplugging the Pixel from USB, with no physical presence
  needed, verified working even from off the home LAN over Tailscale. See
  the design notes' "Materially de-risked" note on the force-stop single
  point of failure.
- No `adb shell vm console` — confirmed dead end for this VM specifically
  (`hostConsoleName: None`), not a permissions issue. See design notes.
- **SSH works, two ways**:
  1. Direct: `adb forward tcp:2222 tcp:2222` then
     `ssh -p 2222 droid@127.0.0.1` from any machine with that adb
     connection. sshd moved to port `2222` (AOSP's port-forwarder ignores
     ports < 1024). Key-based auth using the same forwarded key already
     trusted on Overmind/Cerebrate — no password set.
  2. **Persistent, no `adb` needed**: a reverse SSH tunnel
     (`pixel-tunnel.service`, systemd, `Restart=always`, runs as `droid`)
     connects outbound to a dedicated `pixel-tunnel` account on Overmind
     and holds open `127.0.0.1:2206` there → `ssh -p 2206 droid@127.0.0.1`
     from Overmind reaches the guest. Tightly scoped credential (own
     ed25519 key generated on the guest, `restrict,port-forwarding,
     permitlisten,from=` on the Overmind side, no shell, no local
     forwarding) — see design notes for the full security shape and the
     verification that actually proved the restrictions work, not just
     that they're configured.
  3. **From the Mac**: `ssh cerebrate-pixel6` — a `~/.ssh/config` alias
     that transparently `ProxyJump`s through `overmind-01` to reach the
     tunnel above. Host keys pinned (fetched through the tunnel, then
     cross-checked against the guest's own host key file over the direct
     `adb forward` path before trusting).

- `cerebrate-pixel6.home.arpa` → `192.168.68.60` is now a real DNS node
  entry (confirmed DHCP reservation, will need updating if this host
  moves to wired) — useful for reachability/wireless-adb, but **not** how
  SSH reaches the guest, since the tunnel's Overmind-side listener is
  deliberately `127.0.0.1`-only. **Two things depend on this IP, not
  one**: the DNS record above, and the tunnel key's `from="192.168.68.60"`
  restriction on Overmind (see design notes) — update both together when
  this host moves to wired, or the tunnel will fail authentication.

## Appliance-readiness changes applied

- `stay_on_while_plugged_in`: briefly set to `7` on 2026-09-16, then
  **reverted to `0` the same day** once corrected — Doze specifically
  requires unplugged+stationary+screen-off, and charging already lifts
  App Standby restrictions, so `7` bought nothing against Doze and instead
  kept the OLED lit continuously on a device that's permanently charging
  and never meant to be looked at (real heat/power/burn-in cost for zero
  benefit). Verified reverted via `settings get global
  stay_on_while_plugged_in`. Not the same thing as the VM-level "Keep
  awake" setting below, which is unaffected by this correction.
- VM-level "Keep awake" (Terminal app → Settings → Advanced, separate from
  the Android-level setting above) set to **1 day** — was Off. This is a
  *timed* duration picker, not a permanent toggle (no "always" option
  exists), so it likely needs periodic re-application; actual renewal
  behavior not yet verified over a multi-day window. See design notes.

## Known gap, deliberately not worked around yet

Wi-Fi power-save cannot be force-disabled via `adb shell` on this Android
version — `cmd wifi help` has no power-related subcommand, and the legacy
`wifi_suspend_optimizations_enabled` global setting doesn't exist in this
build's settings table at all (removed from AOSP, not just defaulted off).
The correct mechanism is a `WifiManager` `WIFI_MODE_FULL_HIGH_PERF` lock
held by running code, not a device setting — deferred to whatever
persistent service Stage 4 builds, which should acquire that lock itself.
Applying an unverified settings key here would be exactly the kind of
undocumented tweak this project's plan explicitly avoids.

## Baseline snapshot (2026-09-16, Stage 1)

Captured once, at first boot after developer setup — not yet a
steady-state/idle-over-time baseline (uptime was 36 minutes, load average
still settling). Revisit before trusting these numbers as "resting":

- Battery: 97%, AC powered, 28.0°C, health good.
- Thermal status: `0` (nominal) across all sensors; TPU at 31.0°C idle.
- Doze: `ACTIVE` (expected — device was actively tethered to a session).
- Battery Saver: off. Screen timeout: 30s.
