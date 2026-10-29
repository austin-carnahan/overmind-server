# scripts

Scripts on Overmind come in three kinds. Put each where its kind belongs.

| Kind | What | Where | Lifetime |
| --- | --- | --- | --- |
| **Reusable tools** | Operator commands run again and again | here, `scripts/` | permanent |
| **Installers** | Idempotent setup that rebuilds host or service state | next to what they set up (`hosts/<host>/`, `services/<service>/`) | permanent: the record of how the host is built |
| **One-off root tasks** | Migrations, cleanups, fixes | the [sudo queue](#the-sudo-queue), never the repo | run once, kept 30 days in `done/` |

To tell an installer from a one-off task, ask: **would we need to run it again to rebuild Overmind?** If
yes, it's an installer. If no, it's a one-off task.

## Tools here

| Script | Does |
| --- | --- |
| `agent-sudo` | Time-boxed passwordless sudo for an agent working as you, and its revocation. Run `sudo agent-sudo grant <hours>`, which uses the root-owned copy |
| `sudo-queue` | Lists and runs one-off root tasks (below) |
| `backup`, `restore` | Back up and restore host state |
| `bootstrap` | First-time host setup |
| `health-check` | Read-only checks of systemd services and mounts |
| `check-repo` | Read-only validation of the repository's examples, links and shell scripts |
| `sync-dns-rewrites` | Apply `hosts/dns-rewrites.yaml` to AdGuard |
| `apply-maintainerr-retention` | Apply the versioned Maintainerr retention policy |
| `cerebrate-models`, `validate-model-catalog`, `stage-model` | Cerebrate model inventory, catalog validation, and staging onto the Pixel |

## The sudo queue

The sudo queue lets agents prepare root work without having sudo. An agent (or anyone in group
`overmind`) writes a task, and a person reviews it and runs it.

- **Writing a task:** a shell script in `/var/lib/overmind/sudo-queue/pending/`. Its first comment lines
  say what it does, why, and how to undo it.
- **Listing tasks:** `sudo-queue`, with no sudo needed.
- **Running a task:** `sudo sudo-queue run <task>`. It takes a root-owned copy, shows you that copy in full,
  asks, and runs exactly what you read. The file can't change between review and run.
- **Afterwards:** the script and its output are kept in `done/` for 30 days. The journal keeps a line per
  run with the script's SHA-256 (`journalctl -t sudo-queue`).

Run the root-owned copies (`/usr/local/sbin/sudo-queue`, `/usr/local/sbin/agent-sudo`), not the
checkout's. The agents can edit the checkout, and these tools run often without a fresh review. Installers
in the checkout are different: run them with sudo after reading their diff (see
[Permissions](../runbooks/openclaw/deployment-and-gateway.md#permissions-and-host-administration)).
