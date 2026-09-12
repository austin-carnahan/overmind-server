# Client: Fire TV (primary, at home)

**Status:** DEFERRED — see [status legend](../../design-notes/README.md#status-legend);
architecture decided, nothing built or tested yet. Supersedes an earlier
"live network read, no local copy" decision — see "Why this changed" below.
See [the full design brief](../../design-notes/overmind_rom_emulator_design_brief.md)
for the complete plan this summarizes.

## The decided shape

```text
ROM sources
    ↓
ROMarr (acquisition, scoring, Prowlarr-backed) → staging
    ↓
Igir (DAT audit / 1G1R / normalization)
    ↓
OVERMIND CANONICAL ROM LIBRARY (/mnt/library/romsets, one tier)
    ↓
read-only SMB, LAN + Tailscale
    ↓
R-Shop on Fire TV — browse full catalog, install/remove selected games
    ↓
local USB cache on the Fire TV
    ↓
RetroArch — launches from local cache, not over the network
    ↓
per-user save namespace (/saves/<user>/)
    ↓
Syncthing-Fork — save backup/sync back to Overmind
```

- **Acquisition**: [ROMarr](https://github.com/BlizzHacker/romarr) — verified
  real and active (166K-game production library, Prowlarr-integrated) before
  adopting it. Writes to staging, not the canonical library directly; Igir
  remains the actual gate.
- **Validation/promotion**: Igir, as already decided — DAT-checksum verify,
  1G1R, aggressive cleanup of non-ROM cruft. One tier, no separate master
  archive (AGENTS.md rule 3) — same as before, unchanged by this revision.
- **Distribution**: canonical library exposed **read-only** over SMB (see
  [file-sharing](../../services/file-sharing/README.md)), reachable via LAN
  at home or Tailscale remotely.
- **Client**: [R-Shop](https://github.com/AverageConsumer/R-Shop) — verified
  real (Flutter/Android, active, SMB + local-cache support) before adopting
  it. Browses the full remote catalog with metadata, downloads selected
  titles to local USB storage, does not launch games itself.
- **Local cache**: a USB flash drive on the Fire TV via OTG adapter — a
  cache, not a source of truth. This is the same caching pattern the
  [travel device](travel-device.md) already needed for offline use, now
  unified into one mechanism rather than two.
- **Play**: RetroArch launches from the local cache — not over the network —
  deliberately, for consistent performance on optical-disc systems (PS1,
  Dreamcast) where real-time network seeks would be the rougher path.
- **Saves**: per-user namespace (`/saves/<user>/`), not per-device — a user's
  save state follows them across whichever device they're on. No
  locking/merge machinery needed as long as this shape is preserved from the
  start.
- **Save sync**: [Syncthing-Fork](https://github.com/Catfriend1/syncthing-android)
  (a real, actively maintained — 2,803★ — community continuation of
  Syncthing's Android client), not a custom sync service.

## Why this changed

An earlier version of this doc decided "live network read, no local copy at
all," reasoning that RomM's stack was over-scoped for a single canonical
copy with no sync problem. That reasoning about RomM specifically still
holds — it's not adopted. But the *access pattern* has changed: independent
research surfaced ROMarr and R-Shop as real, small, replaceable convenience
layers over the same core (Igir, SMB, RetroArch, Syncthing), and the
local-cache pattern turns out to be worth building anyway — it's what the
travel device already needed for offline use, and it sidesteps real
network-performance risk for optical-disc systems. Rather than build two
different access patterns (live-read at home, cached-copy while traveling),
one mechanism now covers both.

## Not yet verified

Whether R-Shop and RetroArch actually run well on Fire TV's remote-driven,
10-foot UI specifically — both are real, active projects, but their listed
target audience is Android handhelds (Anbernic, AYN, Odin, Retroid), not
Android TV boxes. Both are explicitly treated as thin, replaceable layers
over the core architecture (SMB + Igir + RetroArch + Syncthing) — if either
doesn't work out on real Fire TV hardware, the core stack is unaffected and
a different client-side tool gets swapped in. This needs real hardware
testing, not more research, to resolve.
