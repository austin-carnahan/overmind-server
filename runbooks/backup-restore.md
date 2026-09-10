# Backup and restore

**Status:** PARTIAL — see [status legend](../design-notes/README.md#status-legend);
destination and tool are selected below, but `scripts/backup` and
`scripts/restore` do not yet perform operations and exit nonzero.

## Selected approach

- **Destination:** Backblaze B2 (a bucket, not Backblaze's separate Windows/Mac
  Personal Backup product, which has no Linux client). Continues the approach
  used on the previous Overmind host. Use a B2 application key scoped to this
  one bucket, not the account's master key.
- **Tool:** `restic`. Client-side encryption before anything leaves the host
  (B2 never sees plaintext), deduplication so repeated snapshots don't re-charge
  for unchanged data, and `restic forget --prune` for a bounded retention policy
  (exact schedule, e.g. daily/weekly/monthly counts, still to be set once real
  data volume is known).
- **Included, to keep size and cost minimal:** Substrate projects (source/docs,
  not build artifacts/dependencies/venvs), notes, papers, curated datasets/models;
  romset masters; reviewed agent-notes; host config and credential-recovery notes.
- **Excluded as reproducible, not backed up:** Library movies/TV (re-obtainable
  via Radarr/Sonarr/Transmission), romset curated output (regenerable from
  masters, DATs, and Igir), and any service cache/vector index/other state
  already treated as a proven-rebuildable index elsewhere in this repo.
- **Still pending:** bucket and scoped key creation, `restic` repository
  initialization, a separate durable backup of the `restic` repository password
  itself (losing it makes every snapshot unreadable), the actual prune/retention
  schedule, wiring `scripts/backup`/`scripts/restore`, and a real restore test.

## Recovery inputs

- Infrastructure repository and explicit package/service versions.
- Protected credentials and host identities, or documented re-enrollment.
- Unique projects, uncommitted work/worktrees, notes, papers, data, and outputs
  under Substrate; pending unique inputs/proposals under the separate Inbox.
- ROM masters as required, saves, manually curated metadata, and media per policy.
- Application-consistent private databases, task/approval history, annotations,
  accounts, and other valuable service state, including SSD-backed native paths.

Only omit data known reproducible. A vector database may contain valuable manual
metadata; do not infer disposability from its name. Public models/media may have
retrieval options, while custom assets may not. Record each policy explicitly.

## Before implementing a backup command

1. Select an independent destination, encryption/secret handling, retention, and
   capacity. A second directory on the same SSD is not disk-loss protection.
2. Inventory sources by ownership and actual backing path; avoid duplicate bind
   mount traversal and accidental omission of service volumes outside Substrate.
3. Use each service's consistent snapshot/export/stop procedure for live state.
4. Report all errors; a missing expected source is a failure, not silent success.
5. Restore samples to an isolated location, then test one service-state recovery.
6. Document recovery of credentials, ownership/modes, and mount dependencies.

## Restore and rollback

Verify the backup and intended targets first. Restore to temporary alternate
locations before replacing live state. Stop the owning service for procedures
that require it, preserve the prior version/state, restore ownership, and run
service-specific verification. If verification fails, stop the service and revert
to the preserved state/configuration using its supported downgrade constraints.
Never restore a database into concurrent use by multiple instances.
