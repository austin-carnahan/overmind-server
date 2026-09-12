# File sharing

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend);
[compose.yaml](compose.yaml) below, not yet deployed.

## Selected implementation

[`ghcr.io/servercontainers/samba`](https://github.com/ServerContainers/samba) —
real, actively maintained (changelog entries through 2026), confirmed
`linux/amd64`/`arm64`/`arm`. Exports `/mnt/library/romsets` **read-only**,
both at the bind-mount level (`:ro`) and in the Samba share config itself —
defense in depth for a share that exists purely to distribute a library, not
accept writes.

One dedicated Samba account (`romsets`), scoped to this one share — not a
general Overmind login, not reused anywhere else.

Driver: [the Fire TV's access pattern](../../runbooks/clients/fire-tv.md) —
R-Shop browses this share and caches selected titles to local USB storage;
RetroArch then plays from the local cache, not live over this share. Reached
via LAN at home or Tailscale remotely, never port-forwarded.

## Still to decide

Whether other Library collections (movies/TV, Substrate) ever get their own
shares through this same container — not committed yet, this pass is scoped
to romsets only. Do not export service-private databases or grant access to
the entire SSD regardless of what gets added later.
