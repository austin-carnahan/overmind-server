# Travel ROM Sync

**Likely unnecessary as a custom tool now.** The primary at-home Fire TV
pattern (see [Fire TV (primary, at home)](../clients/fire-tv.md)) adopted the
same local-USB-cache mechanism this travel case needs — via
[R-Shop](https://github.com/AverageConsumer/R-Shop), which already does
"browse the remote catalog, select titles, download to local storage." A
travel device is just this same client, pre-loaded before a trip rather than
cached on-demand. Build a bespoke `travel-rom-sync` tool only if R-Shop
proves insufficient for that specific pre-trip-bulk-selection workflow once
actually tested.

Saves still need the per-user namespace (`/saves/<user>/`) and
[Syncthing-Fork](https://github.com/Catfriend1/syncthing-android) sync
decided in the primary doc — a travel device without connectivity just
means its saves sync whenever it's next reachable, not never.
