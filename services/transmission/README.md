# Transmission

Status: planned downloader. [settings.example.json](settings.example.json) is a
partial, non-deployable configuration example using proposed paths and a loopback
RPC binding. It omits credentials and must be checked against the chosen version;
it is not a replacement for a running daemon's complete configuration.

Download into `/var/spool/overmind/torrents`, retaining incomplete/completed
and seeding states explicitly. Library promotion is a separate validated step.
Copy and verify imports in v1. Enable hardlinks only after testing the importer's
mount view; separate bind mounts can prevent them even on one SSD. Retain download
data until both import verification and seeding policy allow removal.

Private resume/session state belongs at supported service locations outside
Substrate. Back it up according to the actual daemon's procedure. Restrict
management to authenticated private access; an example binding alone does not
implement network or authentication policy.

Before deployment choose the supported method/version, state/cache paths and SSD
backing, credentials, required mounts, and health/recovery/rollback procedures.
Verify the [outbound VPN boundary](../pia/README.md) before unattended use.
