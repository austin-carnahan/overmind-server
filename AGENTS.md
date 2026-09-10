# AGENTS.md

## Purpose

Overmind is the infrastructure repository, host pattern (`overmind-01`, etc.),
and acting intelligence. Substrate is where humans and agents work; Library is
the passive archive; Inbox is the universal loading dock drained by Overmind.
Bag of Holding is a retired historical name.
Read [README.md](README.md) and [the design index](design-notes/README.md) first.

## Non-negotiable rules

1. **Never expose SSH, SMB, Transmission RPC, Radarr/Sonarr/Bazarr, Pi-hole admin, or Jellyfin admin directly to the public Internet.** Use Tailscale or another explicitly approved private overlay.
2. **Never commit secrets.** Passwords, PIA credentials, API keys, Tailscale auth material, subtitle-provider keys, and private hostnames belong in ignored local secret files or secret stores.
3. **Never destructively rewrite the romset master/archive library.** Curated libraries are outputs; master source data remains immutable.
4. **Never point Kodi/EmulationStation at raw torrent or quarantine directories.** Only promoted canonical libraries are user-facing.
5. **Incoming content is untrusted.** Scan and validate before promotion.
6. Prefer idempotent scripts, explicit paths, and observable health checks.
7. Do not silently change filesystem layout, service ownership, ports, or network topology. Document architectural changes first.
8. For torrent privacy, encrypted DNS is not a VPN. PIA (or equivalent outbound VPN) must remain the egress privacy boundary for Transmission where configured.
9. Remote-access VPN and outbound-privacy VPN are separate concerns: Tailscale gets **into** the home network; PIA gets **out** privately.
10. Keep low-powered Pi services conservative. Heavy transcoding, subtitle synchronization, and high-end emulation belong on the future mini-PC unless explicitly tested.
11. **Never let an agent/runner use a human's personal or forwarded git credentials.** Each agent gets its own scoped, revocable, expiring credential covering only the repo(s) it touches. See [git credentials](design-notes/security-model.md#git-credentials).

## Ownership and filesystem boundaries

- `/opt/overmind` is the proposed deployed checkout. Other project repositories
  remain independent; never import the archived Substrate tree wholesale.
- `/mnt/substrate` is the collaborative surface, optionally attached per
  instance. Projects own their code, docs, temporary notes, inputs, and outputs.
- Shared work collections are `notes/`, `papers/`, `datasets/`, and `models/`.
  `/mnt/library` is the sibling archive for movies, TV, and ROMs.
  Do not restore the old projects/workspaces split or `staging/`.
- `/var/spool/overmind/{documents,media,torrents}` is the Inbox. Its routing and
  quarantine rules determine promotion to Substrate or Library. It is outside
  both destinations. Preserve pending unique inputs until successful import.
- Service databases, vector stores, runtime state, and generic caches live at
  each service's own default locations, documented in `services/<name>/`.
  There is no imposed shared state/cache hierarchy. Selected paths and Inbox
  may be SSD-backed; logical ownership and disk placement are separate.
- SSD identity, filesystem, physical mount mappings, users/groups, and service
  deployment methods are not yet verified. Never invent them as installed facts.
- Check required mounts before starting dependent services. Never recursively
  grant a common group write access to the whole SSD or Substrate.
- Media paths are under `/mnt/library`; quarantine stays within typed Inbox
  workflows. Torrent completion, promotion, and seeding retention are distinct.
  Preserve master ROMs and unique saves separately from curated outputs.
- Generated is not disposable. Protect task history, annotations, unique model
  weights/datasets, retained outputs, and uncommitted work. Only proven caches
  may be rebuilt. Use application-consistent backups for live databases.
- Worktrees prevent editing collisions, not unauthorized access. Scope agent
  credentials/execution, and access shared services through supported interfaces.

## Repository organization

`hosts/` selects machine roles/settings; `services/` owns deployment notes and
service helpers; `agents/` contains shared authored behavior; `runbooks/` contains
operational procedures. `design-notes/history/` is historical evidence, not a
source of current instructions. Current design docs take precedence over it.

## Change procedure

Before implementing a new service or automation:

1. Update architecture/runbook docs if the change alters behavior.
2. Add or update an example configuration with no secrets.
3. Add a verification command or health check.
4. Make scripts fail closed where practical.
5. Preserve rollback instructions.

## Preferred style

- Bash: `set -euo pipefail`.
- Config: examples committed, secrets ignored.
- Systemd: explicit user/group, restart policy, and dependencies.
- Filesystems: use the documented stable logical paths; keep physical mount
  mappings explicit. Follow each service's default state/cache locations.
- Validate with `scripts/check-repo`; do not describe scaffold checks as a live
  deployment test. Incomplete bootstrap/backup/restore operations must report
  that clearly and must not mutate the host or claim success.
