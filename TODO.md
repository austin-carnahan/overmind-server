# Overmind backlog

## First pass completed

- [x] Rename the scaffold to Overmind and establish the agreed repository layout.
- [x] Consolidate the current design and retain discussion history.
- [x] Separate collaborative/archive content from each service's default state/cache.
- [x] Replace misleading/destructive setup and recovery stubs.
- [x] Preserve media/ROM workflows and add research/agent service plans.

## 1. Inspect and establish the foundation

- [x] Inspect overmind-01: exact Ubuntu release, RAM, architecture, packages, services.
- [x] Identify the SSD/filesystem by stable identity; record its existing contents:
      2 TB SABRENT (JMicron JMS579) USB SSD, reformatted ext4, empty. See
      [host README](hosts/overmind-01/README.md) for the UAS quirk this
      enclosure needs to avoid crashing the Pi's USB controller.
- [x] Decide SSD backing for `/mnt/substrate`, `/mnt/library`,
  `/var/spool/overmind`, and selected service-default locations: single ext4
  partition, bind-mounted per logical path; `/var/spool/overmind` not yet
  moved off the microSD.
- [ ] Define per-project/service ownership and required-mount startup behavior.
- [x] Choose an independent backup destination and secret/host-identity recovery:
      Backblaze B2 + restic, see [backup-restore.md](runbooks/backup-restore.md).
      Bucket/key creation and repository init are still pending.
- [x] Document and test host networking, SSH, private remote access, and reboot:
      Tailscale enrolled, OpenSSH + agent-forwarded key, VS Code Remote-SSH, reboot verified.
- [ ] Implement bootstrap only after those manual procedures are verified.
- [x] Demonstrate remote project editing, one media/game client, and sample restores.
      Remote project editing works (VS Code Remote-SSH). Media client
      demonstrated end to end: Radarr search → Transmission download → import
      into `/mnt/library/movies` → Jellyfin playback, all confirmed working.
      Sample restores (backup side) still pending.

## 2. Repeatable daily use

- [x] Implement service definitions using verified ARM-compatible deployment methods.
      Transmission + PIA (gluetun), Paperclip, Jellyfin, Radarr, Sonarr,
      Bazarr, Prowlarr, and a Cloudflare-bypass proxy all deployed and
      running. See [services/README.md](services/README.md) for the full list.
- [ ] Verify Transmission's private egress and failure behavior before unattended use.
      Deployed; kill-switch/failure test still pending.
- [ ] Establish manual media/ROM checks and imports, then resolve automation gating.
      Movie pipeline validated end to end (see above), still fully manual —
      no decision made yet on what (if anything) becomes automatic. ROM/romset
      pipeline not yet exercised at all.
- [ ] Select research capture, citation/attachment ownership, and note synchronization.
- [ ] Define shared dataset manifests, versioning, and project-local data practices.
- [ ] Establish [shared agent notes v1](design-notes/agent-notes-v1.md): short
  Substrate instructions, an index, documents-intake candidates, and one explicit integration.
- [ ] Choose offline media selections and explicit note/save conflict handling.
- [ ] Implement application-consistent backups, restore checks, and health reporting.

## 3. Bounded agent work

- [ ] Deploy Paperclip and one runner using supported configuration/state locations.
      Paperclip + Postgres containers running on SSD-backed storage; no runner
      configured and no pilot task run yet (see
      [services/paperclip/README.md](services/paperclip/README.md)).
- [ ] Define scoped credentials, worktree lifecycle, limits, review, output retention.
- [ ] Test state recovery and ordinary project work with orchestration stopped.

## 4. Expand from actual needs

- [ ] Add search/vector services with private state and rebuildable-index policies.
- [ ] Add local inference, higher-end emulation, transcoding, or game streaming.
- [ ] Assign additional Overmind hosts without changing content ownership contracts.

## ROM pipeline and Fire TV access — architecture decided (v2), nothing built yet

Revised 2026-09-12 after independent research; supersedes the earlier
live-network-read decision. Full plan:
[design brief](design-notes/overmind_rom_emulator_design_brief.md),
summary: [Fire TV client doc](runbooks/clients/fire-tv.md).

- [ ] **Acquisition**: deploy [ROMarr](https://github.com/BlizzHacker/romarr)
      against staging, backed by Prowlarr (already running). Test one
      static-console collection first.
- [ ] **Validation/promotion**: the deterministic pipeline — DAT-validate
      (Igir) → 1G1R filter → aggressive cleanup of non-ROM cruft → promote to
      `/mnt/library/romsets/<system>` (one tier, see
      [ingestion](services/ingestion/romsets/README.md)).
- [ ] **Distribution**: read-only SMB export of the canonical library (LAN +
      Tailscale) — see [file-sharing](services/file-sharing/README.md).
- [ ] **Fire TV client**: sideload [R-Shop](https://github.com/AverageConsumer/R-Shop),
      configure a USB OTG local cache, confirm it actually browses/downloads
      well with a Fire TV remote — the real unverified question, needs real
      hardware, not more research.
- [ ] **Play**: RetroArch launches from the local cache; confirm its built-in
      thumbnail downloader box-arts the library automatically once
      standard-named.
- [ ] **Saves**: per-user namespace (`/saves/<user>/`), synced via
      [Syncthing-Fork](https://github.com/Catfriend1/syncthing-android) — not
      a custom sync service.
- [ ] **Nice-to-have**: RetroAchievements via RetroArch's native support.
- Both RomM and the "live network read, no local copy" access pattern were
  considered and dropped — RomM's strengths (box art, save sync) turned out
  free once local caching was already the right call for other reasons
  (optical-disc performance, unifying with the travel-device pattern).

## Inherited media work to retain

- Prior scaffold records a first Mega Drive DAT/Igir cleanup workflow.
- Continue NES/SNES/N64 curation; handle PS1/Dreamcast multi-disc sets and saves separately.
- Assess Radarr/Sonarr/Bazarr, Jellyfin, travel caches, and optional independent DNS.
- The old microSD/256 GB drive migration tasks are superseded by the reported
  fresh Ubuntu installation and 2 TB SSD. Their completion was not inferred.
