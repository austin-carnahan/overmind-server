> Historical discussion snapshot. See the [current design index](../README.md) for the implemented repository structure and current decisions.

# Repository, storage, and naming boundaries

Date: 2026-09-09
Status: Proposed for discussion; no migration or deployment performed.
Builds on: [initial proposal](2026-09-09-unified-home-server-proposal.md).

Superseded as the current overview by the [consolidated platform design](2026-09-09-platform-design.md).
In particular, `home-server` is only the local session name, and shared datasets
now have an explicit place. This note retains the earlier discussion context.

Revision: Consolidate projects and workspaces following user feedback. Projects
own their documentation, including temporary working notes. Drop `workspaces/`
and `staging/`. The flat shared `notes/`, `papers/`, and `inbox/` names below are
the revised proposal, not yet confirmed naming decisions.

## Starting hardware

User-reported current host: Raspberry Pi 4 with a fresh Ubuntu Server 26 LTS
installation, a 128 GB microSD card, and a connected 2 TB SSD. RAM, exact OS
release, SSD filesystem, current mount, and backup destination have not been
inspected. These unknowns do not prevent deciding the logical boundaries below.

## One platform and one infrastructure repository

Recommend `home-server` as the canonical infrastructure repository. Bag of
Holding can become the friendly name for the whole environment: the place that
holds media, research, projects, and computing tools. Substrate can remain a
conceptual name for the research/knowledge capabilities or simply a historical
name. It does not need its own directory, server stack, or infrastructure repo.

The former Bag of Holding media design becomes one set of capabilities inside
the platform. Substrate contributes its paper/vault/project conventions. Shared
access, storage, deployment, agent execution, models, and recovery belong to the
platform. Media apps and research apps use those facilities independently.

Names are presentation choices. The durable architectural boundaries are between
deployment instructions, content, application state, and disposable outputs.
Use direct content names in the filesystem: `projects`, `notes`, and `papers`.

## Proposed Git repository

```text
home-server/
  README.md
  AGENTS.md
  .gitignore
  design-notes/                 # proposals, decisions, rationale
  hosts/
    overmind-01/                # nonsecret inventory, roles, mount/path settings
  services/
    jellyfin/                  # deployment definition, example config, README
    transmission/
    paperclip/
  agents/                      # shared authored instructions and workflows
  scripts/                     # small setup/check/backup helpers as needed
  runbooks/                    # rebuild, restore, import, client setup
```

Entries illustrate ownership; creating all services or empty directories is not
a milestone. Add them as they become useful. A service directory should explain
its version, configuration, required storage and permissions, health check, and
recovery procedure. Keep host settings ordinary configuration consumed by the
chosen tools; do not build a custom deployment language.

Keep one home for each definition: service-specific configuration lives with its
service; host settings select location and deployment; project-specific agent
instructions live with the project. Shared agent material here should only be
material actually reused. Paperclip application-owned settings need documented
exports/backups rather than a manually maintained second source of truth.

The existing local `home-server/` directory is a design workspace containing two
historical copies, not yet the finished repository layout. Once agreed, promote
selected Bag of Holding material into this layout and adapt it. Keep the old
Substrate copy out of the new infrastructure repository; its useful content
belongs in live collections or independent projects. A short provenance note can
link historical material. Do not commit the entire archive to preserve history.

## Proposed live storage

Use the SSD for durable payloads, active work, application state, and substantial
runtime writes. Reserve the microSD primarily for the OS and host configuration.
An infrastructure checkout could live at `/opt/home-server`; the checkout itself
contains no live payloads or application databases. Installed host config such as
mount definitions and service units remains in the OS's normal locations.

Proposed direct SSD mount at `/mnt/home-server`, consistent with the previous
stable-mount convention. Start with one filesystem and ordinary directories;
this is not a partition plan. The actual mount/format operation requires a disk
inventory and is outside this proposal.

```text
/mnt/home-server/
  media/
    movies/
    tv/
    music/
    games/
      masters/                 # preserved original ROM/disc source collection
      library/                 # curated games for clients
      saves/                   # valuable mutable data, separate from ROMs
  projects/
    <project>/                 # code, research, docs, working notes, outputs
  notes/                       # shared personal knowledge; proposed Obsidian vault
  papers/                      # shared paper/reference collection
  models/                      # shared weights and model assets
  state/<service>/             # durable application-owned files/databases
  cache/<service>/             # only outputs proven disposable/rebuildable
  inbox/
    media/                     # downloads awaiting checks/import
    papers/                    # papers awaiting filing/import
```

The media libraries and torrent downloads must remain on the same filesystem for
hardlink imports. Container volume mappings must also preserve a usable shared
filesystem view. A service receives only its required subdirectories: a shared
SSD does not mean shared write access to everything. Do not carry the old
recursive media-group permission script onto this broader tree.

Use `state` instead of the ambiguous `data`: papers and movies are also data.
Treat all service state as valuable by default. Split out caches only where the
application supports it and rebuildability is established; do not force every
app's internal directory layout to match this tree. Configure large container
image/build storage on SSD during deployment rather than accidentally consuming
the OS card. Bound logs through the normal logging tools rather than designing
a new top-level log hierarchy.

No live `services/` or general `agents/` directory is needed here. Deployed
application definitions are in Git, their runtime state is under `state`, code
runs in projects, and retained outputs belong to their project. This prevents
an agent artifact collection from becoming a competing project archive.

## One home per project

Every project lives under `projects/<project>/`, whether it is software, research,
writing, or a mixture. It owns its documentation, design decisions, temporary
working notes, project-specific inputs, and retained outputs. No parallel
Substrate project hub is required.

A single-repository software project can use that directory as its Git root.
A non-code project need not use Git. A project needing several repositories can
contain them in its own directory; choose that structure only when necessary.
Large/private files can belong to a project without being committed. Git ignore
rules and backup rules are separate decisions. Temporary working notes stay
with the project and should not be automatically discarded solely because they
are called temporary.

Do not prescribe a folder template for every project. Existing repository
conventions remain valid. Additional agent/human worktrees are execution copies
of the same project, not a second content domain. Their physical placement can
be chosen with the execution tooling later; no top-level `workspaces` category
is needed. Uncommitted work in those copies can be valuable.

An agent's identity does not determine where its output belongs. Code changes
belong in a project branch; a retained report or working note belongs to that
project; task execution history belongs to Paperclip state.

## Shared notes and Obsidian

Propose `notes/` as the shared Obsidian vault: personal notes, cross-project
knowledge, reusable techniques, literature maps, and general paper notes.
Obsidian is the chosen interface to that collection, not the owner of all
Markdown files on the server.

Project-specific notes remain in their project, including exploratory or
unfinished ones. Distill reusable insights into a shared note when useful and
reference the originating project; do not mirror the entire project note tree.
A paper discussion about one project's method belongs to that project; a general
summary useful across projects can live in the shared notes collection.

If seeing project notes through Obsidian becomes important, decide the viewing
arrangement separately. Do not duplicate content or make a web of filesystem
links just to force all notes into one vault. The shared `notes/` directory may
have independent version control/synchronization and backup; it stays outside
the infrastructure repository.

The shared `papers/` collection holds reusable references. Projects reference
shared papers and own their project-specific annotations/analysis. Citation and
attachment management still needs a tool-specific decision before implementation.

## Replace staging with explicit intent

Use `inbox/` for material awaiting review or filing. It is not a universal scratch
directory. Quarantine remains an explicit state/subdirectory in the appropriate
import workflow; nothing becomes trusted just by arriving in the inbox.

Keep project scratch work within its project, and service processing scratch in
an appropriate service cache/temp location. Unique working files are not caches.
Create a dedicated `downloads/` area later only if an application's retention or
seeding requirements make that distinction useful. Required library and download
filesystem relationships still apply regardless of directory names.

## Git, backup, and reproduction

| Material | Infrastructure Git? | How it is recovered |
| --- | --- | --- |
| Deployment definitions, versions, scripts, instructions | Yes | Clone the repository |
| Secret values and private machine/account material | No; commit examples only | Reinject from a protected store or encrypted backup |
| Other software projects | No; independent Git repositories | Clone their remotes and restore unpushed/uncommitted work |
| Papers, notes, datasets, authored deliverables | No | Restore content backup; optional separate Git for suitable text collections |
| Media, ROM masters, saves | No | Restore according to their separate value/replaceability policies |
| Paperclip/Jellyfin databases and other valuable app state | No | Restore an application-consistent backup/export |
| Model weights | No; record versions/retrieval information where needed | Retrieve reproducible public weights; restore custom or unavailable weights |
| Rebuildable indexes, temporary files, downloaded container images | No | Rebuild or retrieve; retain only when practical |

Outside the infrastructure repository does not mean outside version control,
outside backup, or expendable. Conversely, Git alone does not reconstruct a
populated working server. The reproduction contract has three inputs:

```text
versioned infrastructure + protected secrets + restored content/state
                              -> working environment
```

A fresh deployment should establish users, required mounts, paths, services, and
checks. A restore then recovers content and valuable application state. Required
SSD mounts must be verified before dependent services start; a missing SSD must
not silently redirect their writes onto the OS card. Rebuild instructions must
be usable without Paperclip or any other hosted application running.

There is currently one reported data disk. A second copy on that SSD does not
protect against its loss. Choose an independent backup destination before moving
irreplaceable material to this system; no backup product or destination is
selected by this directory proposal.

## Decisions to refine next

1. Accept or revise the naming: `home-server` repository, Bag of Holding as the
   overall friendly name, with Substrate optional as a conceptual/historical name.
2. Refine the flat live tree: `projects/`, shared `notes/` and `papers/`, and
   `inbox/`. Project ownership is unified; shared collection names remain proposed.
3. After agreeing on boundaries, define ownership/permissions, mount settings,
   and the minimum reproducible host setup. Validate these on the actual Pi.

This note records a proposal only. No files from the previous projects were
moved, no Git repository was initialized, and no server commands were executed.
