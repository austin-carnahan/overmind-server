# Client option: Travel Fire TV

Status: inherited client option, not the current host deployment. Validate device/application support before use.

See [Fire TV (primary, at home)](fire-tv.md) — the primary pattern now also
uses a local USB cache (via R-Shop), the same mechanism this travel profile
needs. The two have converged to one mechanism, differing mainly in *when*
titles get cached (on-demand at home vs. pre-selected before a trip), not in
architecture. `travel-rom-sync` (below) is likely unnecessary now — R-Shop
already does "browse remote catalog, select titles, cache locally."

The travel device is a **client and offline cache**, not a source of truth.

Recommended capabilities:

- Kodi/Jellyfin client
- Tailscale
- RetroArch
- curated local ROM cache (NES/SNES/Genesis/PS1 + tested N64)
- Luna / cloud gaming
- future Moonlight client

## Desired UX

```text
HDMI + power -> join network -> controller -> play/watch
```

## Offline fallback

Local ROMs should remain playable with no network connection. This is important for hotel Wi-Fi failures, high-latency international travel, and captive portals.
