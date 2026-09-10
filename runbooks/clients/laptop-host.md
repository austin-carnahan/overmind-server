# Client option: Laptop + Fire TV

Status: inherited client option, not the current host deployment. Validate device/application support before use.

Minimum-hardware reference deployment.

## Laptop

Acts as:

- downloader
- canonical movie/TV storage host
- ingestion/organization host
- SMB file server for Kodi
- optional Jellyfin server

Internal or external storage may be used. Paths should be configurable rather than hard-coded to Linux/Pi locations.

## Fire TV

Runs:

- Kodi or Jellyfin client
- Tailscale (optional remote access)
- RetroArch local travel cache
- normal streaming apps
- Luna / other supported cloud gaming

## Local-media flow

```text
Laptop library -> SMB/Jellyfin -> Fire TV -> TV
```

## Goal

A user with only a laptop and inexpensive streaming stick should be able to reproduce the core experience without Raspberry Pi hardware.
