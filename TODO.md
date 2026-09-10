# Overmind backlog

## First pass completed

- [x] Rename the scaffold to Overmind and establish the agreed repository layout.
- [x] Consolidate the current design and retain discussion history.
- [x] Separate collaborative/archive content from each service's default state/cache.
- [x] Replace misleading/destructive setup and recovery stubs.
- [x] Preserve media/ROM workflows and add research/agent service plans.

## 1. Inspect and establish the foundation

- [x] Inspect overmind-01: exact Ubuntu release, RAM, architecture, packages, services.
- [ ] Identify the SSD/filesystem by stable identity; record its existing contents.
      Blocked: SSD not yet acquired.
- [ ] Decide SSD backing for `/mnt/substrate`, `/mnt/library`,
  `/var/spool/overmind`, and selected service-default locations. Blocked on SSD.
- [ ] Define per-project/service ownership and required-mount startup behavior.
- [x] Choose an independent backup destination and secret/host-identity recovery:
      Backblaze B2 + restic, see [backup-restore.md](runbooks/backup-restore.md).
      Bucket/key creation and repository init are still pending.
- [x] Document and test host networking, SSH, private remote access, and reboot:
      Tailscale enrolled, OpenSSH + agent-forwarded key, VS Code Remote-SSH, reboot verified.
- [ ] Implement bootstrap only after those manual procedures are verified.
- [ ] Demonstrate remote project editing, one media/game client, and sample restores.
      Remote project editing works (VS Code Remote-SSH); media client and
      sample restores still need Library storage (blocked on SSD).

## 2. Repeatable daily use

- [ ] Implement service definitions using verified ARM-compatible deployment methods.
      Transmission + PIA (gluetun) deployed; Jellyfin/Radarr/Sonarr/Bazarr not started.
- [ ] Verify Transmission's private egress and failure behavior before unattended use.
      Deployed; kill-switch/failure test still pending.
- [ ] Establish manual media/ROM checks and imports, then resolve automation gating.
- [ ] Select research capture, citation/attachment ownership, and note synchronization.
- [ ] Define shared dataset manifests, versioning, and project-local data practices.
- [ ] Establish [shared agent notes v1](design-notes/agent-notes-v1.md): short
  Substrate instructions, an index, documents-intake candidates, and one explicit integration.
- [ ] Choose offline media selections and explicit note/save conflict handling.
- [ ] Implement application-consistent backups, restore checks, and health reporting.

## 3. Bounded agent work

- [ ] Deploy Paperclip and one runner using supported configuration/state locations.
- [ ] Define scoped credentials, worktree lifecycle, limits, review, output retention.
- [ ] Test state recovery and ordinary project work with orchestration stopped.

## 4. Expand from actual needs

- [ ] Add search/vector services with private state and rebuildable-index policies.
- [ ] Add local inference, higher-end emulation, transcoding, or game streaming.
- [ ] Assign additional Overmind hosts without changing content ownership contracts.

## Inherited media work to retain

- Prior scaffold records a first Mega Drive DAT/Igir cleanup workflow.
- Continue NES/SNES/N64 curation; handle PS1/Dreamcast multi-disc sets and saves separately.
- Add artwork/scraping after canonical names stabilize.
- Assess Radarr/Sonarr/Bazarr, Jellyfin, travel caches, and optional independent DNS.
- The old microSD/256 GB drive migration tasks are superseded by the reported
  fresh Ubuntu installation and 2 TB SSD. Their completion was not inferred.
