# Backup and restore

Status: design checklist; `scripts/backup` and `scripts/restore` do not perform
operations and exit nonzero. No backup destination/tool has been selected.

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
