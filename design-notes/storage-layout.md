# Storage and ownership

**Status:** PROPOSED — see [status legend](README.md#status-legend). Physical
disk mappings, permissions, and service installations require host inspection
before implementation.

**Overmind** is the repo, host pattern, and acting intelligence. **Substrate** is
where work happens. **Library** is where archived things sit. **Inbox** is the
universal loading dock, drained by Overmind into the appropriate destination.

```text
/opt/overmind/                    # deployed infrastructure repository
/mnt/substrate/                   # optional collaborative surface
  projects/<project>/             # code, docs, working notes, inputs, outputs
  notes/
    agents/                       # reviewed shared agent knowledge
  papers/
  datasets/
  models/
/mnt/library/                     # sibling passive archive
  movies/
  tv/
  music/                          # when needed
  romsets/                        # Client-facing tier: further curated down
                                   # to a small browsable/playable set from
                                   # romsets-archive/. The only tier exposed
                                   # to SMB/R-Shop/clients.
  romsets-archive/                # DAT-verified, broadly-curated (1G1R,
                                   # language/region filtered) archive tier,
                                   # kept indefinitely so acquisition and
                                   # first-pass Igir validation don't need
                                   # repeating. Not exposed to any client.
                                   # Re-acquisition, not a further backup, is
                                   # the fallback if this is damaged.
  saves/                          # per-user namespace, not per-device
    <user>/                       # e.g. saves/austin/ — see fire-tv.md
/var/spool/overmind/               # Inbox, outside both destinations
  documents/
    agent-notes/                  # proposed reusable lessons awaiting review
  media/                          # one subfolder per type, so ingestion can
    movies/                       # route on arrival path; pending-review/
    tv/                           # quarantine is a state within these
    romsets/                      # folders, not a separate directory
    music/                        # when needed
```

Transmission's incomplete-download working directory is the downloader's own
state, not a logical Overmind path (see [transmission](../services/transmission/README.md)).
Only completed, seeding-safe downloads become ordinary arrivals under
`media/<type>` above; seeding retention still gates when that copy can be
removed. There is no separate `torrents/` Inbox root.

The archive's internal subdivisions are examples to refine as content arrives.

Romset saves: decided as a per-**user** namespace, not per-device
(`/mnt/library/saves/<user>/`, see
[Fire TV client doc](../runbooks/clients/fire-tv.md)) — a user's save state
follows them across devices, so different users never conflict even on the
same game, and no locking/merge machinery is needed as
long as this shape is preserved from the start. Synced via Syncthing-Fork,
not a custom sync service. No live save migration is implemented yet.

## Service internals

There is no imposed service-state or cache hierarchy. Each service keeps its
own default locations, documented under `services/<name>/` for the actual chosen
version/deployment. Do not invent paths for an application that is not installed.
This includes databases, vector stores, credentials, runtime state, and caches.

Selected directories may be backed by SSD storage using suitable mounts or volume
mappings without changing the paths the application expects. State outside
Substrate/Library can be irreplaceable. Treat indexes as disposable only when all
valuable contents are reproducible. Project-local metadata/caches can stay where
the project's native tooling expects them.

Concrete example: `/var/lib/overmind/curation/<platform>/identified.json` and
`cache/skyscraper-resources/` (see
[curate/README.md](../services/ingestion/romsets/curate/README.md)) look like
disposable cache by location, but are the output of hours of rate-limited
third-party API calls — not reproducible in seconds like the rest of that
service's derived files. Same durability posture as `romsets-archive/`
above, just kept at its own service-default path rather than under
`/mnt/library`, per this doc's "no imposed service-state hierarchy" rule.

## Logical paths and physical disks

- microSD: Ubuntu, host configuration/identity, recovery tools, deployed checkout.
- SSD: Substrate, Library, Inbox where useful, and selected large/high-write
  application storage at service-default paths.
- Independent backup destination: still to be selected.

One SSD can back all these locations. Neither Substrate nor Library represents
the entire disk.

**Physical mounts and logical paths live in deliberately separate subtrees**,
decided 2026-09-14 after an earlier flat layout put a physical disk
(`/mnt/ssd`) and logical paths (`/mnt/substrate`, `/mnt/library`) side by side
under `/mnt`, which was confusing and didn't scale to a second disk:

```text
/mnt/disks/<name>/         # physical mounts — an implementation detail no
  ssd1/                     # service config ever references directly.
    substrate/               # Numbered (ssd1, ssd2, ...) rather than
    library/                 # matched to the filesystem's own label —
    var-lib-overmind/        # simpler to scale to another disk. The actual
    downloads/               # ext4 label (e.g. overmind-ssd) can still
    models/                  # differ; nothing depends on them matching.

/mnt/substrate              # logical — the only paths services reference
/mnt/library                # bind-mounted from a /mnt/disks/<name>/ subdir
/mnt/downloads
/mnt/models
/var/lib/overmind
```

`/mnt/models` (added 2026-09-17 for the Cerebrate Pixel 6 model cache, see
[models/README.md](../models/README.md)) is deliberately a sibling of
`/mnt/substrate`, not a subdirectory of it, despite `/mnt/substrate/models/`
appearing in the tree above — the two are different things. A runtime's
own downloaded weight cache is a service internal (see "Service internals"
below and [services/inference/README.md](../services/inference/README.md)),
not project-owned Substrate content; Substrate remains free to grow its own
`models/` later for curated/reusable artifacts a project deliberately
keeps, without colliding with anything a runtime manages on its own.

A second disk mounts at `/mnt/disks/<next-name>` with no naming
collision, and backs whatever new logical path(s) it's meant for without
touching any existing bind mount. Adding one is a decision about what it
backs, not a namespace problem.

Verify storage before dependent writers start so absent mounts do not fill the OS
card. Only roles requiring a given surface depend on its attachment. Shared SSD
backing still means a shared failure boundary. Keep basic host administration and
recovery independent of attached collections. Do not relocate all of `/var`.

## Ownership

- Each project owns its docs, temporary notes, datasets, experiments, and retained
  outputs. There is no workspaces split or duplicate research project hub.
- Shared datasets use versioned collections and small origin/retrieval manifests;
  projects own their transformations. Large files need not be committed to Git.
- General notes belong under Substrate notes, including the proposed
  [agent knowledge collection](agent-notes-v1.md). Personal/project work remains
  usable without a note-indexing service or orchestrator.
- Runtime weight caches/vector indexes are service internals; curated model
  artifacts or embedding datasets used in projects can be Substrate content.
- Passive archives remain available to clients and designated importers. Protect
  the romset library from destructive curation — DAT validation at ingestion
  is the only safety net now that there's no separate master tier. A project
  actively analyzing media owns its analysis/output in Substrate and can
  reference source files in Library.
- Apply scoped permissions; do not make every client/agent a writer to all roots.

## Inbox routing and retention

Inbox contains arrivals, not ordinary project scratch or a second archive.
Quarantine/pending-review states live inside the relevant typed intake workflow.
V1 uses manual or explicitly invoked imports, with existing application hooks
only where validated; there is no universal inbox daemon.

| Intake | Possible destination |
| --- | --- |
| `documents` | Substrate papers, notes, datasets, or a project |
| `documents/agent-notes` | Reviewed entries under Substrate notes/agents |
| `media/movies`, `media/tv` | Reviewed Library movies/TV, or project-specific media |
| `media/romsets` | Reviewed romsets, promoted into either Library tier (see above) |
| `media/music` | Reviewed Library music, when needed |

Process only completed inputs. Verify the destination before removing an intake
copy. Failed/rejected items remain isolated for review. Pending unique documents
and note proposals need backup; spool placement is not permission for automatic
expiration. Retained torrent data stays until its seeding policy allows removal.

Separate mounts can prevent hardlinks even when backed by one SSD. V1 can copy
and verify. Enable hardlink imports only after testing a common compatible mount
view inside the actual importer/container. Do not assume cross-root renames are
atomic. Record the importer's mount arrangement in its service documentation.
Linux documents the cross-mount restriction in [link(2)](https://man7.org/linux/man-pages/man2/link.2.html).

See [backup and restore](../runbooks/backup-restore.md) for recovery categories.
