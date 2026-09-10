# Jellyfin

Status: planned, optional media application; no installation verified.

Read canonical movies, TV, and music under `/mnt/library`. Clients must not
see the inbox or quarantine. Restrict content write access unless a selected
feature requires it. Keep private database/accounts/watch history outside
Substrate at supported state paths; preserve them in application-consistent backups.

Begin with a direct-play workflow; Pi transcoding capability is unverified.
Kodi may remain a client. Before deployment choose version/method, credentials,
private endpoints, native state/cache locations and SSD backing, required mounts,
health checks, restoration, and rollback.
