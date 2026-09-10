# Rebuild overmind-01

Status: planning procedure; automation is intentionally unavailable.

## Prerequisites

Record the [host inventory](../hosts/overmind-01/README.md), tested OS/image,
independent content/state backup, and protected identity/credential recovery.
Inspect existing disks before any formatting. Preserve the installed root/boot
mount configuration when adding SSD mappings.

## Sequence to validate

1. Install the selected Ubuntu Server image and establish local SSH/networking.
2. Clone the Overmind infrastructure repo, targeting `/opt/overmind` for deployment,
   using a repo-scoped deploy key for this first checkout (see
   [git credentials](../design-notes/security-model.md#git-credentials)).
3. Identify SSD contents/filesystem and establish the agreed physical mounts.
4. Expose work at `/mnt/substrate`, archive content at `/mnt/library`, and intake
   at `/var/spool/overmind`. Back selected service-default locations with SSD
   directories as needed, using verified bindings and explicit dependencies.
5. Apply scoped users/groups/permissions and restore protected host identities.
6. Restore or attach canonical content and application-consistent service state.
7. Deploy only selected, verified services; inject credentials separately.
8. Check private access, mount dependencies, and VPN failure behavior where needed.
9. Verify remote project editing, curated media access, and restored sample files.
10. Test reboot and absent-SSD behavior; verify required services fail closed.

Use `scripts/bootstrap --plan` for a reminder, not installation. Run
`scripts/health-check` with the actual selected systemd units; application-specific
checks still apply. Recovery and rollback are described in
[backup and restore](backup-restore.md).
