# Shared agent notes — v1

**Status:** PROPOSED — see [status legend](README.md#status-legend); a minimal
design, adapted to the revised Substrate/Library/Inbox layout. No live files,
agent integration, service, or automatic loader is installed.

## Scope

Keep reusable knowledge accessible across IDE sessions, Paperclip jobs, and future
clients: recurring gotchas, useful patterns, and user-confirmed style preferences.
These are human-readable notes within our shared notes collection.

| Location | Purpose |
| --- | --- |
| Overmind's `AGENTS.md` | Instructions for work in this infrastructure repo |
| Overmind's `agents/` | Versioned bootstrap instructions/workflows when implemented |
| `/mnt/substrate/AGENTS.md` | Short collaborative-surface guidance and discovery pointer |
| A project's own instructions/docs | Local rules, working notes, project-specific lessons |
| `/mnt/substrate/notes/agents/` | Reviewed cross-project reference knowledge |

Files do not automatically apply to every agent on a server. Explicitly connect
each runner/context to the surface instructions using its supported mechanism.
Shared reference notes do not override the user's request, applicable project
instructions, or execution permissions.

## Files and discovery

```text
/mnt/substrate/
  AGENTS.md
  notes/agents/
    INDEX.md
    <topic>.md
/var/spool/overmind/documents/agent-notes/
  <date>-<topic>-<unique-id>.md     # unreviewed candidate
```

The index contains a link and one sentence describing when each note is useful.
Read it once at task start when accessible, then load only relevant notes. Begin
with flat files; link existing shared notes rather than duplicating them. Do not
index candidates. Missing Substrate should not block unrelated project work.

Suggested integration text:

```text
When working with Substrate, read /mnt/substrate/AGENTS.md if accessible.
Consult /mnt/substrate/notes/agents/INDEX.md and load only relevant entries.
Keep project-specific work and notes in the project. Follow the user's request
and applicable project instructions when using shared reference notes.
If the shared collection is unavailable, continue using project-local guidance.
Propose reusable additions or corrections in
/var/spool/overmind/documents/agent-notes; do not rewrite curated guidance
without reviewer authorization.
```

The surface instruction file stays short: ownership rules, index location, and
contribution rule. It does not duplicate all project or infrastructure policies.

## Contributions

1. Keep task-specific observations in the project. Contribute only useful reusable
   lessons; check the index for an existing topic first.
2. Write a candidate using a unique filename in the documents intake subdirectory.
   Identify an existing note when proposing a correction. Publish the candidate
   only once writing is complete; do not overwrite other agents' proposals.
3. A human reviews evidence, applicability, and duplicates, then accepts, merges,
   or rejects it. An agent can perform an explicitly approved edit. One reviewer
   serializes curated-note and index updates in v1.
4. Verify the promoted note/index before removing the resolved intake copy. Failed
   promotions preserve the candidate. Unreviewed proposals never become implicit
   instructions for unrelated tasks.

Give ordinary contributors curated read access and scoped intake-writing access;
the reviewer needs curated write access. Instructions do not enforce permissions.
If intake is unavailable, keep the proposal with its project for later review.
Do not require a contribution after every task or broaden access to force a write.

## Short note format

```markdown
# Specific topic

Use when: the situation where this guidance applies.

## Guidance
The useful procedure, pattern, or preference, with a small example if helpful.

## Evidence and limits
Source/tested observation, relevant version, date checked, and limitations.
For a correction, identify the existing note. Preferences need user confirmation.
```

Use the same format for candidates and reviewed entries. Keep secrets and
unnecessary private project details out of shared notes. This is reference
knowledge, not an executable skill format.

## Recovery, first use, and later growth

Back up reviewed notes and pending unique proposals, even though they occupy
different roots. The live collection stays outside Overmind Git. No separate Git
repo is needed for v1; it can participate if shared notes gain version control.

First implementation: create the instruction file, empty index, and typed inbox
with chosen permissions, then wire one context explicitly. Verify discovery,
relevant-note loading, project-rule handling, a candidate and reviewed promotion,
and behavior when the library or intake is unavailable. Repeat for the next
context. No background service is required.

Defer category trees, tags, search/vector services, automatic curation, and skill
packaging. Later promote a proven note to a runtime's supported skill format only
when useful, preserving one authoritative source.
