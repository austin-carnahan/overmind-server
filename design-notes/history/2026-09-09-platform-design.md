> Historical discussion snapshot. See the [current design index](../README.md) for the implemented repository structure and current decisions.

# Overmind: consolidated platform design

Date: 2026-09-09
Status: Current discussion draft. Naming agreed: Overmind is the repository,
host pattern, and acting intelligence; Substrate is an optionally attached
collaborative surface. Bag of Holding is retired. Proposed paths are
`/opt/overmind` and `/substrate`. Agreed: generic service state/cache stays outside
Substrate at conventional service paths, with SSD backing where useful. Exact
physical mount mappings remain to be designed. No migration or deployment has
been performed.

This consolidates the initial proposal and repository/storage discussion. It
incorporates the user's preference for a flat storage layout, one home per
project including all working notes, and removal of `workspaces` and `staging`.
`home-server` is only the local session directory name, not the intended final
project or repository name.

## Purpose and naming

Build a durable personal computing environment accessed through interchangeable
clients: laptop IDEs, research tools, agents, media players, and travel devices.
Start on the existing Pi and expand compute/storage roles when needed.

**Overmind** is the repository (`overmind`), the host pattern (`overmind-01`,
`overmind-02`, ...), and the acting intelligence. The name describes both the
whole environment and the mind operating through it. Bag of Holding is retired;
historical reference copies retain their original names for provenance.

**Substrate** is primarily the collaborative work surface consumed and edited
by humans and agents: projects, notes, papers, datasets, and reusable authored
assets. It also holds the media collection that client devices consume or
contribute to. It is optionally attached per Overmind instance; an instance can
have roles that do not require a Substrate attachment.

Services and scripts can serve, index, import, and modify that material on behalf
of its users. The boundary follows the material's purpose and ownership, not the
identity of the process touching a file. Their private databases, vector stores,
runtime state, and caches belong to the service layer outside Substrate.

The Overmind repository describes how to establish and maintain instances and
their capabilities. Substrate content is shared through explicit access and
ownership rules. Attaching a surface does not grant universal write access or
make concurrent edits safe automatically. Applications continue to own their
private service state and expose supported interfaces to collaborators.

## Hardware and physical placement

User-reported host: Raspberry Pi 4, fresh Ubuntu Server 26 LTS, 128 GB microSD,
and a connected 2 TB SSD. Exact release, RAM, disk filesystem, current mount,
and backup destination remain uninspected.

- microSD: OS, installed host configuration, small infrastructure checkout.
- SSD: content, projects, models, application state, caches, downloads, and
  substantial container/runtime writes configured during deployment.
- Independent backup destination: still to be selected; a directory on this SSD
  cannot protect against loss of the SSD.

Proposed logical paths are `/opt/overmind` for the infrastructure checkout and
`/substrate` for the collaborative surface. The top-level Substrate path is the
current recommendation from the mount-prefix discussion; `/srv/substrate` is
the conventional alternative. No mount has been configured.

Substrate no longer names the entire physical SSD. Heavy application state and
caches can live on the same SSD while remaining outside the collaborative
surface. Prefer retaining conventional service paths and backing selected paths
with SSD directories through bind mounts when useful; use supported runtime
volume mappings where appropriate. The SSD can
still use one filesystem with separate directories for these purposes. Physical
mounts and mappings will be designed next; avoid mounting the whole SSD at
`/substrate` and keeping instance-private state inside that surface.

On this Pi, sharing one SSD also means sharing its failure/availability boundary.
Logical separation does not keep SSD-backed services running if the disk is
unplugged. Only roles that require Substrate depend on its attachment; any other
service still depends on the availability of its own backing storage. Independent
storage is needed if these must remain physically detachable independently.

Collections and project directories live directly under `/substrate`; there is
no extra project-name wrapper and no required `/etc/overmind` directory.

## MicroSD and installed host configuration

Keep Ubuntu's standard filesystem organization. The card provides the operating
system and an independently usable administration/recovery environment; our
repository supplies the deliberate configuration changes. Do not create a
second custom OS hierarchy or move all of `/etc`, `/var`, or `/home` onto the SSD.
Keep the installer's boot/root layout unless inspection reveals a reason to
change it. The following is a selected logical directory map; service-specific
SSD mounts may appear inside it, so it is not a full physical disk inventory:

```text
/                              # Ubuntu root filesystem on microSD
  boot/                        # Ubuntu-managed boot assets
    firmware/                  # Pi boot partition, as mounted by the image
  etc/
    fstab                      # filesystems to mount, including the SSD
    netplan/                   # host networking
    ssh/                       # SSH configuration and host keys
    systemd/system/            # our installed service units and overrides
    docker/                    # daemon configuration, if Docker is selected
  opt/
    overmind/                  # deployed infrastructure Git checkout
  home/
    <admin>/                   # login environment and personal SSH settings
  usr/                         # Ubuntu/package-managed programs and libraries
    local/bin/                 # optional small locally installed commands
  var/
    lib/                       # host and service state; selected paths on SSD
    log/                       # bounded system logs
    cache/                     # host/service caches; large caches on SSD
  substrate/                   # optional collaborative surface, SSD-backed here
```

This follows the standard roles of `/etc`, `/usr`, `/opt`, and `/var` in the
[Filesystem Hierarchy Standard](https://specifications.freedesktop.org/fhs/latest-single/).
Ubuntu's [network configuration](https://ubuntu.com/server/docs/explanation/networking/configuring-networks/)
uses Netplan; its [Pi boot documentation](https://documentation.ubuntu.com/hardware-support/boards/explanations/piboot-ab/)
describes the boot partition. Preserve the release-specific internal boot layout.

The deployed checkout under `/opt` is an operational copy of the same Git repo
edited from a laptop or project checkout. Deploy a deliberate revision and run
an explicit configuration application step. A pull or an agent editing a source
file must not silently alter the running host. Keep the deployed checkout under
administrative control rather than granting general project agents write access.

Version only the host settings we manage: package selections, mount settings,
network setup where needed, SSH policy, logging limits, and unit overrides.
Source templates can live under `hosts/overmind-01/`; reusable service definitions
live under `services/<service>/`. Install selected files into Ubuntu's native
locations with appropriate ownership/modes, retaining backups for rollback.
Prefer supported configuration drop-ins where available. Do not put all of
`/etc` into Git or symlink the whole directory into the repository. Existing
installer/cloud-init configuration must be inspected before replacing it.

For example, a repository mount template contributes the SSD entry to
`/etc/fstab`, an SSH policy drop-in is installed under `/etc/ssh/sshd_config.d/`,
and service units are installed under `/etc/systemd/system/`. These are deployment
examples, not files created by this proposal. Never replace the complete fstab
with a template that omits the installed boot/root filesystems.

Secret values remain outside Git. Native host identities, such as SSH host keys
and remote-access enrollment state, stay in their supported local locations.
Use each service's supported configuration/credential location and secret
injection mechanism, with access limited to the owner/required service. Select
exact credential paths when deploying that service. No current requirement
justifies a separate custom Overmind configuration/secret directory. Document
secure recovery or re-enrollment of each identity rather than treating the card
as entirely disposable.

Keep SSH, networking, and recovery tools usable without the SSD. Applications
requiring SSD storage must wait for and verify the mount before starting. Bulk
container/runtime storage and hosted application databases belong on SSD, while
essential host/package state stays on the card. Configure each tool's supported
storage settings, with explicit mount dependencies. Docker and containerd may
need separate storage configuration depending on the installed engine/backend;
Docker's `data-root` alone does not move a separate containerd image store. See
[Docker's daemon storage documentation](https://docs.docker.com/engine/daemon/).

Bound host logs and ordinary caches; do not add a custom logging hierarchy.
The OS remains reinstallable through package/configuration records, while
protected host identities are separately recoverable. Test both an ordinary
reboot and boot with the SSD absent when implementing this boundary.

## Canonical infrastructure Git repository

```text
overmind/
  README.md                    # purpose, map, getting started
  AGENTS.md                    # repository-wide instructions and boundaries
  .gitignore
  design-notes/                # proposals, decisions, rationale
  hosts/
    overmind-01/               # host inventory, roles, mount/path configuration
  services/
    jellyfin/                  # deploy definition, example config, service notes
    transmission/
    paperclip/
  agents/                      # shared authored instructions/workflows as needed
  scripts/                     # small operational helpers
  runbooks/                    # rebuild, restore, imports, client setup
```

This repository describes how to reproduce and operate the environment. Other
projects are independent repositories/collections, not subdirectories committed
to this infrastructure Git history. The existing local session directory and
historical copies are not the intended contents of the final repository.

Responsibilities:

- `hosts`: which machine runs which roles and where required storage lives.
- `services`: how an application is deployed, configured, upgraded, checked, and
  restored. Prefer upstream-supported deployment patterns and small independent
  Compose stacks where suitable; use native services when simpler for host or
  hardware integration. Validate the actual host/runtime before implementation.
- `agents`: genuinely shared authored material. A project's own agent
  instructions stay with that project. `AGENTS.md` governs work in this repo;
  `services/paperclip` deploys the orchestrator; `agents` contains reusable
  behavior. Application-owned Paperclip configuration is backed up/exported,
  rather than manually duplicated into another supposed source of truth.
- `scripts`: limited glue around tools, added after a manual procedure is known.
- `runbooks`: procedures usable by a person even when hosted applications fail.

Commit examples, versions, configuration, instructions, and appropriate small
assets. Keep secrets, live databases, content collections, model weights, and
runtime outputs outside this repo. Each new service must identify its required
paths, permissions, health check, state, backup procedure, and rollback.

## Substrate: collaborative surface

```text
/substrate/
  projects/                    # each project owns its complete working material
    <project>/
  notes/                       # shared personal knowledge / proposed Obsidian vault
  papers/                      # shared reference documents and portable metadata
  datasets/                    # shared, reusable datasets
  media/
    movies/
    tv/
    music/
    games/
      masters/                 # preserved ROM/disc source collection
      library/                 # curated client-facing collection
      saves/                   # valuable mutable state
  models/                      # reusable model weights, adapters, associated assets
  inbox/<domain>/              # arrivals awaiting review, validation, or filing
```

The names express ownership and purpose. Create directories when used. Apps may
retain their native internal layouts; split caches only when supported and
actually safe to discard. Keep torrent downloads and library destinations on
the same filesystem, with container mounts that preserve hardlink imports.

Project-local scratch and temporary working notes stay with the project.
Service processing scratch belongs in the service's supported temporary/cache
location. `inbox` is for incoming material; quarantined content has an explicit
quarantine location/state within its import workflow and is never indexed as
canonical content. Seeding retention can be handled within the media download
workflow without redefining the entire top-level layout.

## Why service state and cache move outside Substrate

The earlier layout put these directories in Substrate for physical/operational
convenience: keep high-write data off microSD, locate runtime volumes explicitly,
and make valuable application state easy to include in recovery. That would fit
a definition of Substrate as the entire portable service environment, including
its databases. Those benefits do not require the directories to belong to the
collaborative surface, however. Cache also should not inherit the backup policy
of valuable content merely because both reside on the SSD.

Agreed: with Substrate optionally attached per instance, keep generic
application-private state/cache outside it. Otherwise attaching a content
collection would also attach a service's operational history or private database,
and services could acquire unnecessary dependencies on that surface. Multiple
instances must not treat attachment as permission to concurrently open the same
live database. Collaborators use the owning service's API where appropriate.

Default logical locations for system services are `/var/lib/<service>` for
durable state and `/var/cache/<service>` for regenerable caches, following the
[FHS state/cache distinction](https://specifications.freedesktop.org/fhs/latest-single/).
Use the actual package/runtime's supported paths; these are conventions, not
claims about a particular Paperclip installation. Container volumes can map the
chosen host storage to the app's expected internal paths. Moving a service to
another instance includes a deliberate state migration or shared service endpoint,
not simultaneous access to its private files.

| Material | Ownership and placement |
| --- | --- |
| Paperclip database, task/approval history, runtime sessions | Private service state; back up consistently |
| Jellyfin accounts, watch history, private database | Private service state; back up consistently |
| Vector database storage | Conventional service state; only treat as rebuildable if all valuable contents can be reproduced |
| Rebuildable thumbnails/search indexes | Service cache; rebuild only when known safe |
| Project notes, retained agent outputs, unique experimental results | Project-owned content in Substrate |
| Game saves, curated metadata sidecars, portable annotations | Domain-owned content in Substrate |
| Project-local build caches or vault-local app metadata | May remain with their project/collection when native tooling expects it; classify backup/retention separately |

The distinction is ownership and lifecycle, not file format or whether software
generated the data. State outside Substrate can be irreplaceable. State inside
a project can be proper collaborative content. If an application keeps valuable
annotations only in its database, back up that database; do not invent a shadow
file store or call it disposable. Portable exports may complement that backup.

There is no blanket ban on a cache within a project or collection. The decision
removes catch-all platform `state/` and `cache/` directories from Substrate and
avoids requiring app-specific internal layouts to be rewritten.

Similarly, curated model artifacts or embedding datasets used as project inputs
can be collaborative assets. An inference runtime's private downloaded-weight
cache or a search service's internal vector index remains service-owned. File
type alone does not assign either to Substrate.

## Projects, shared collections, datasets, and models

Each project owns its code, docs, decisions, temporary working notes, private
inputs, experiments, and retained outputs. A project can be a Git checkout,
contain multiple repositories when needed, or be a non-code collection. Existing
project conventions take precedence over inventing a universal folder template.
Agent worktrees are additional execution copies of a project; physical placement
will follow the runner's needs, with unique/uncommitted work protected.

Shared collections hold material useful independently of one project. Project
notes remain in projects; general notes live in `notes`. Distill and link useful
insights rather than maintaining duplicate note trees. Obsidian is a client for
notes; any future cross-project viewing arrangement must preserve ownership.

Dataset placement follows ownership, not size or whether machine learning uses it:

| Example | Proposed location |
| --- | --- |
| Phytophany-only image inputs | `projects/phytophany/datasets/` or its existing equivalent |
| A corpus used by several projects | `datasets/<name>/<version>/` |
| A project's processed subset or experiment outputs | Inside that project's dataset/output directories |
| Small synthetic test fixtures | Versioned in the relevant project's Git repo |
| Shared model weights/tokenizers/adapters | `models/<name>/<version>/` |
| Experimental checkpoints from one project | That project's experiment/output area |
| Disposable search embeddings/indexes | Service cache outside Substrate when proven rebuildable |

Large files do not need to move outside their owning project solely to stay out
of Git. Ignore payloads in the project's Git configuration and back them up
according to value. Directory ownership, version control, and backup are
separate decisions. A shared dataset belongs outside the infrastructure repo,
even if its small manifest is versioned independently.

For a shared dataset, begin with a small README/manifest recording origin,
version, retrieval or generation procedure, applicable usage terms, and checksums
when useful. Consumers reference that version and write transformations to their
own output locations. Preserve source versions rather than silently editing a
shared source. Avoid a custom data registry or mandatory dataset-management tool
until an actual need appears. Fine-tuned weights and unique derived datasets may
be irreplaceable despite being generated.

## How the environment works

1. **Access:** clients connect privately; retain the Tailscale direction, with
   SSH/IDE access for development and application-specific media/research clients.
   Private network access and each application's permissions are separate layers.
2. **Applications:** service definitions deploy applications that read/write
   only their assigned content and state paths. Each service owns its database.
   Media, research, and agents can be operated independently.
3. **Agent work:** Paperclip coordinates; runners work on scoped projects;
   retained outputs remain project-owned. Paperclip history and runtime state
   stay in Paperclip's private service state outside Substrate. Worktree
   separation is not security isolation.
4. **Media:** incoming content is validated before promotion, ROM masters remain
   preserved, saves are protected separately, and clients see curated libraries.
   Torrent egress privacy remains distinct from inbound remote access.
5. **Compute:** models are shared assets consumed by inference services. Add
   heavier inference, transcoding, or game streaming on a capable machine when
   needed. Use configured service endpoints so clients need not know placement.
6. **Offline use:** selected notes/media can be replicated to clients with
   explicit conflict behavior, especially for saves. Git handles code exchange.
   Synchronization and worktree copies do not replace backups.

## Recovery and growth

Recovery combines versioned deployment instructions, protected secrets, and
restored content/application state. Git alone recreates an empty environment;
backups recover the valuable contents. Preserve uncommitted work, unique notes,
papers, datasets, models, saves, and useful application history. Rebuild only
what is known to be disposable; restore databases consistently with the app's
supported procedure.

Required storage must be mounted before dependent services start. Missing SSD
storage must not redirect service writes onto the OS card. Use basic health,
capacity, and backup checks with bounded logs. Deliberate upgrades and per-service
rollback keep maintenance manageable. Keep any future dedicated DNS host
independent of the main compute/media host.

Stages remain:

1. Establish mounts, ownership, private access, recovery, remote editing of one
   project, and playback of a small canonical media/game collection.
2. Make daily workflows repeatable: research capture, imports, selected sync,
   service deployment, and health reporting.
3. Add one bounded Paperclip workflow with scoped execution, resource/cost limits,
   retained outputs, human review, and tested state recovery.
4. Add richer search, local inference, storage, or another compute node based on
   actual needs while preserving content ownership and access interfaces.

Next design decisions: actual SSD mount/filesystem and permissions, backup
destination, then the first deployable host/service slice.
No existing directories have been renamed or reorganized by this note.
