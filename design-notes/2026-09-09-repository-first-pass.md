# Repository first pass — 2026-09-09

**Status:** HISTORICAL — see [status legend](README.md#status-legend); no host deployment or storage migration.
Current paths and ownership are in [storage](storage-layout.md); the
[surface refinement](2026-09-09-surface-layout-refinement.md) supersedes the path
choices recorded below.

The user authorized using the existing Bag of Holding directory to construct
Overmind. It was renamed to `overmind`. The local design discussion was moved
into this repo's `design-notes/history`, with current architecture/storage notes
extracted into maintained documents. The external archived Substrate copy remains
untouched and outside the repository.

## Structural changes

- `profiles/pi-home-server` becomes `hosts/overmind-01` with reported hardware and
  explicitly unknown deployment details.
- Client profiles become client runbooks; future mini-PC ideas become design notes.
- `docs` becomes current design notes and recovery runbooks.
- `ingestion` moves under `services/ingestion`; ROM curation notes become runbooks.
- `agents` defines shared behavior ownership; Paperclip, research, inference, and
  file-sharing service plans make the broader scope visible.
- Documentation examples now use `/opt/overmind`, `/substrate`, and conventional
  service state/cache paths. Historical snapshots retain old proposals verbatim.

## Stub corrections

- Remove the installer that recursively changed permissions and installed media
  packages before mount/network/privacy decisions were settled.
- Remove the example unit referring to a nonexistent ingestion worker.
- Replace the incomplete backup copier with a non-mutating failure and a recovery
  design checklist; it must not report a successful backup after ignored errors.
- Bootstrap prints an explicit plan; actual setup remains unavailable.
- Health checks target explicitly selected units and optional required mount,
  returning failure for failed checks and unsupported-host errors clearly.
- Fix `.gitignore` so Markdown documentation is not mistaken for Mega Drive ROMs.
- Keep validators as manual components; they do not implement automatic promotion.

No runtime volumes, disks, private credentials, host users, or installed services
were modified. An independent backup destination, actual mount mappings, service
versions, and ARM deployment methods are still required before implementation.

## Validation

- Initialized a local Git repository on `main`; no remote or commit was created.
- `scripts/check-repo --require-shellcheck` passed: 49 Markdown files/local links,
  one JSON example, six Bash scripts, and documentation/example ignore rules.
- ShellCheck 0.11.0 passed using temporary tooling outside the repository.
- 23 temporary behavior checks passed using mocked Linux/service/scanner commands:
  healthy/inactive/missing services, mount success/failure, argument errors,
  scanner/probe error propagation, and non-mutating setup/recovery stubs.
- Current documents/examples contain no obsolete media-root or deployed-project
  paths. Old paths remain only in explicitly historical discussion snapshots.

These are repository and script-behavior checks. The Pi, mount layout, real
scanners, VPN behavior, and application deployments have not been tested.
