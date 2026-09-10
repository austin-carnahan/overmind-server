# Surface and intake refinement

**Status:** PROPOSED — see [status legend](README.md#status-legend); no host mount or service migration performed.

Overmind is the repo, host pattern, and acting intelligence. Substrate is where
work happens. Library holds the passive archive. Inbox is the universal loading
dock, drained by Overmind into the destination that wants the material.

The updated roots are `/opt/overmind`, `/mnt/substrate`, `/mnt/library`, and
`/var/spool/overmind/{documents,media/{movies,tv,romsets,music}}`. Transmission's
incomplete-download state is its own working directory, not one of these
roots; only completed, seeding-safe downloads land under `media/<type>`. Each
service's state/cache remains
at its own defaults, documented for the selected version/deployment. There is no
mandatory shared state/cache path convention.

This supersedes the earlier root-level Substrate path, media and intake within
Substrate, and the suggested generic `/var/lib/<service>` / `/var/cache/<service>`
layout. Historical discussion and the initial first-pass record remain snapshots.
Current [storage documentation](storage-layout.md) and examples use the new roots.

The [agent-notes v1](agent-notes-v1.md) stays small: reviewed Markdown and an index
under Substrate notes, a short surface instruction file, and candidates under
`/var/spool/overmind/documents/agent-notes`. Review is human-led; no worker or
skills framework is required. Pending proposals need backup as well as notes.

Physical mappings remain to be verified. Separate bind mounts can invalidate
hardlink assumptions despite using one SSD; copy-and-verify is a safe first
import method until the actual importer mount layout has been tested.

Validation: repository link/JSON/shell checks and ShellCheck passed. The health
helper now takes repeatable `--mount` arguments instead of `--substrate`; 26
mocked behavior checks passed, including multiple mounts and a missing second
mount. No actual mount, importer, runner, or application deployment was tested.

Live-save placement is provisionally emulator-native with optional archive
exports, pending the user's preference. Existing saves are not moved.
