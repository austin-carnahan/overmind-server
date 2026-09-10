# Future compute

**Status:** DEFERRED — see [status legend](README.md#status-legend); not a second deployed host.

Additional instances use the Overmind host pattern; create inventory when real
hardware exists. Preserve the same content and access contracts when migrating
inference, transcoding, emulation, or other heavy work.

Candidates retained from the original design include Jellyfin hardware
transcoding, higher-end emulation, Sunshine/Moonlight streaming, larger storage,
and local inference. Keep Pi workloads conservative until measured. A headless
Ubuntu server should not implicitly gain a local gaming desktop.

An instance may operate without a Substrate attachment. Services requiring content
must declare that dependency; others may consume remote service endpoints.
Private application databases require deliberate migration, not concurrent access
merely because multiple machines can see the same files.
