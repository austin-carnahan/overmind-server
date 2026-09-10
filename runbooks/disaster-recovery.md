# Disaster recovery

Status: desired order; must be exercised on the selected deployment.

1. Recover network basics and local host administration independently of Substrate.
2. Recover the deployed repo, protected identities/credentials, and host config.
3. Inspect surviving disks and establish the recorded mounts/permissions.
4. Attach or restore Substrate, Library, pending unique Inbox inputs, and each
   service's private state at its documented defaults.
5. Start selected services after their required storage is verified.
6. Verify representative project files, saves, private service history, and clients.
7. Rebuild disposable client caches and proven derived indexes as needed.

Use [backup and restore](backup-restore.md). Git alone cannot recover content or
private databases, and synchronization/travel caches are not independent backups.
