# Runbooks

**Status:** PROPOSED — see [status legend](../design-notes/README.md#status-legend); host deployment and restore are not yet tested.

- [Rebuild overmind-01](rebuild-overmind-01.md)
- [Backup and restore](backup-restore.md)
- [Disaster recovery](disaster-recovery.md)
- [Ingest media](ingest-media.md)
- [Add a ROM](add-new-rom.md)
- [Configure a travel device](configure-fire-tv.md)
- [Remote project work](clients/remote-work.md)
- [Kodi](clients/kodi.md), [Fire TV (primary)](clients/fire-tv.md),
  [travel device](clients/travel-device.md),
  [alternate laptop host](clients/laptop-host.md), [optional DNS host](clients/optional-dns-host.md)
- Romset notes: [DATs](romsets/dats.md), [Igir](romsets/igir.md),
  [scraping](romsets/scraper.md), [travel sync](romsets/travel-sync.md)

Each implemented procedure must state prerequisites, steps, verification, and
rollback. Document actual host findings rather than substituting example paths
or old device assumptions. Repository checks do not validate a live host.
