# Architecture

**Status:** PROPOSED — see [status legend](README.md#status-legend); implementation remains a scaffold.

**Overmind** is the infrastructure repo, host pattern (`overmind-01`, etc.), and
acting intelligence. **Substrate** is the optionally attached collaborative
surface under `/mnt/substrate`. **Library** at `/mnt/library` holds the passive
archive. **Inbox** at `/var/spool/overmind` receives typed arrivals for Overmind
to route. The Bag of Holding name is retired.

Humans and agents own work in projects. Shared notes, papers, datasets, reusable
model artifacts belong in Substrate; passive media belongs in Library. Services may serve,
index, or edit these materials on behalf of users; their private databases,
vector stores, caches, and operational state stay at each service's own defaults,
documented in its service directory. No common state/cache convention is enforced.

## Repository responsibilities

| Directory | Responsibility |
| --- | --- |
| `hosts/` | Inventory, role selection, and machine-specific configuration |
| `services/` | Application deployment plans, examples, and service helpers |
| `agents/` | Shared authored behavior; project instructions remain project-owned |
| `scripts/` | Small operations with clear effects and exit status |
| `runbooks/` | Manual setup, verification, recovery, client workflows |
| `design-notes/` | Decisions and rationale; history is explicitly historical |

The proposed deployed checkout is `/opt/overmind`. Apply selected configuration
to native host locations deliberately. Other projects are independent Git repos
or collections under Substrate; payloads and service state are outside this repo.

## Initial host and roles

[overmind-01](../hosts/overmind-01/README.md) is a Pi 4 with fresh Ubuntu Server,
128 GB microSD, and a 2 TB SSD. Host inspection is pending. Start with SSH/private
access, storage/recovery, remote project work, and a modest media workflow.
A GUI, RetroPie base, local display, and hardware acceleration are not assumed.

Keep services independently deployable, using supported tools and plain
configuration. Evaluate small Compose stacks where suitable and native services
for host integration. Exact methods and versions are selected per service after
inspection. No custom scheduler, dataset registry, or universal ingestion engine
is required by this design.

Paperclip coordinates bounded project work. Runners require scoped execution,
credentials, resource/cost limits, and human review. Ordinary project work and
host recovery must work without orchestration. Worktrees are execution copies,
not security boundaries or another content category.

## Growth

1. Verify mounts, access, recovery, one remote project, and one media/game workflow.
2. Make daily imports, capture, selected sync, deployments, and checks repeatable.
3. Add one Paperclip workflow and prove state recovery before expanding agents.
4. Add compute/storage roles when measured needs justify them.

Inference services use configured endpoints so higher-compute hosts can take
over without changing client contracts. An optional separate DNS host remains
independent of media/compute. See [future compute](future-compute.md).
