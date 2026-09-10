# overmind-01

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
hardware is owner-reported, host inspection and provisioning are pending.

| Item | Reported value |
| --- | --- |
| Machine | Raspberry Pi 4 |
| OS | Fresh Ubuntu Server 26 LTS |
| OS storage | 128 GB microSD |
| Attached storage | 2 TB SSD |

Unverified: exact OS release, RAM, architecture, SSD identity/filesystem/content,
current mounts, accounts/groups, network addressing, and installed services.

## Intended first roles

Private remote project work and modest media access, supported by tested storage
and recovery. Substrate and Library are separate optional attachments;
Inbox has its own verified backing and intake permissions. Do not assume RetroPie, a GUI,
a local display, or hardware acceleration. DNS on another device is optional.

[paths.env.example](paths.env.example) records proposed logical paths only. No
script automatically sources it and no installer creates those paths. Service
state locations must come from the selected application's supported deployment.

Before implementation, record read-only inspection, decide SSD bindings and
per-service ownership, then follow [rebuild-overmind-01](../../runbooks/rebuild-overmind-01.md).
Keep private host details and secret values in ignored local files/stores.
