# Client option: Travel Fire TV

Status: inherited client option, not the current host deployment. Validate device/application support before use.

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
