# Security boundaries

**Status:** PROPOSED — see [status legend](README.md#status-legend); these are requirements for future deployment, not a hardening report.

- Private LAN/overlay access is the default. Keep administrative services off the
  public Internet and retain application authentication inside the private network.
- Use native protected credential locations or a supported secret mechanism.
  Commit examples only. Recover or re-enroll host identities deliberately.
- Services and agents receive only the content paths and credentials they need.
  An agent's worktree is not an execution sandbox. Avoid broad privileged mounts.
- Incoming files remain untrusted through quarantine, scan, type/archive checks,
  and domain validation. A successful ffprobe or malware scan is one check, not
  proof of safety or permission to bypass the rest of the import gate.
- Validate romsets against DAT checksums before promotion into the archive
  tier (`/mnt/library/romsets-archive/<system>` — DAT-verified, broadly
  curated, kept indefinitely); further curate from there into the
  client-facing tier (`/mnt/library/romsets/<system>` — the only tier exposed
  to SMB/R-Shop). Re-acquisition, not a preserved-original copy, is the
  fallback if the archive tier itself is damaged by a destructive operation —
  validate before promoting, dry-run before any destructive Igir run.
  Preserve other unique mutable content (saves). Automated library managers
  must not bypass the validation gate.
- Transmission's outbound VPN, private remote access, and DNS privacy are distinct.
  Verify fail-closed download behavior without breaking host administration.
- Consider `noexec,nodev,nosuid` only for compatible payload/import paths. Projects
  need to execute code; do not blindly apply media mount policy to all Substrate.
- Missing required mounts must prevent dependent service writes. Protect native
  state even when backed by SSD; never apply one recursive ownership/mode policy.
- Prefer deliberate application upgrades and tested security-update policy.
  Bound logs and verify backup/restore before trusting unattended operations.

## Git credentials

- Human interactive git access, across any repo, uses the person's own SSH key
  via agent forwarding (`ssh -A`) from their client machine. The private key
  never lives at rest on a host.
- Bootstrapping a fresh host's first checkout of this repository, before an
  interactive session or agent forwarding is configured, may use a repository
  deploy key scoped to Overmind only — read-only unless that host also needs
  to push. A deploy key is repo-scoped, not identity-scoped: every process
  using it is indistinguishable, so treat it as a bootstrap convenience, not a
  long-term credential for ongoing work.
- Agents/runners never reuse a human's forwarded key or a shared deploy key.
  Each gets its own credential, scoped to only the repo(s) it touches, with an
  expiry: a fine-grained GitHub personal access token for now, a short-lived
  GitHub App installation token once Paperclip mints per-job credentials.
  Revoking one agent's access must not affect another's.
- Bind git identity to the working directory, not global config: `~/.ssh/config`
  `Host` aliases with `IdentitiesOnly yes`, or `.gitconfig` `includeIf
  "gitdir:..."` blocks. This prevents an agent worktree from accidentally
  pushing under a human's identity by running from the wrong directory.

## Inter-host service credentials

The same rule as git credentials above — every agent/process gets its own
scoped credential, never a shared or personal key — applies beyond git.
First real example: `cerebrate-pixel6`'s reverse SSH tunnel to Overmind
(2026-09-16) uses a dedicated `pixel-tunnel` system account
(`/usr/sbin/nologin`, no password) and a key generated on the Pixel's
Debian guest that never leaves it, restricted on the server at both the
account level (`sshd_config` `Match User`) and the individual key
(`authorized_keys` `restrict,port-forwarding,permitlisten=,from=`) —
redundant on purpose. See the
[Pixel 6 inference node design notes](2026-09-16-pixel6-inference-node.md)
for the full shape, including a documented residual limitation: the server
can restrict where a reverse tunnel listens, but not what the client dials
on the far end — a real asymmetry between what the server can prove and
what the client claims, worth remembering for any future reverse-tunnel
credential, not something this pattern solves.

See [AGENTS.md](../AGENTS.md), [storage](storage-layout.md), and
[service onboarding](../services/README.md).
