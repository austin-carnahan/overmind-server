# Content ingestion

**Status:** PROPOSED — see [status legend](../../design-notes/README.md#status-legend).
There is no worker, automatic promotion, watcher, or installable service unit
in this repository.

```text
inbox -> quarantine/review -> scan and validate -> classify -> promote
```

Services may modify content on behalf of people/agents; their processing state
uses each service's defaults. Inbox is `/var/spool/overmind` with a `documents`
subpath and a `media` subpath split by type (`movies`, `tv`, `romsets`, `music`),
so a pipeline can route on arrival path. Quarantine/pending-review is a state
within the matching `media/<type>` folder, not a separate directory. A
completed, seeding-safe torrent download is an ordinary `media/<type>` arrival;
Transmission's own incomplete-download state is not part of this Inbox (see
[transmission](../transmission/README.md)). Route reviewed material to
Substrate or Library; keep project scratch within the project. Begin with
documented manual procedures.
Only process completed inputs and verify destination content before deleting intake
copies; preserve unique pending documents and seeding downloads as required.

Available helpers:

- [security/scan.sh](security/scan.sh): on-demand ClamAV component, no promotion.
- [media/validate-media.sh](media/validate-media.sh): ffprobe container inspection.
- [media workflow](media/README.md), [romset workflow](romsets/README.md),
  [quarantine](quarantine/README.md).

A successful helper is not a full safety guarantee. Checks for types, sidecars,
archives, domain integrity, and manual review remain necessary. Do not enable
library-manager automatic imports until they cannot bypass the validation gate.
Validate romsets against DAT checksums before promotion — the only tier, no
separate archive to fall back on — and ensure permitted writers cannot mutate
promoted content through a shared hardlink unexpectedly.

Before adding a worker, document an actual unmet need, supported integration,
service user/permissions, mounts, private state, health, recovery, and rollback.
Prefer existing application's hooks/imports and small glue where sufficient.
