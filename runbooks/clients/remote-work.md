# Remote project work

**Status:** PARTIAL — see [status legend](../../design-notes/README.md#status-legend);
connectivity and the editor workflow are verified below. Project storage under
`/mnt/substrate/projects` is not yet mounted.

## How to connect

1. Join the tailnet (see [networking](../../design-notes/networking.md));
   overmind-01 is reachable by MagicDNS as `overmind-01` from any tailnet device.
2. Add an SSH config entry so the account and agent forwarding aren't retyped
   each time:

   ```text
   Host overmind-01
       HostName overmind-01
       User austin
       ForwardAgent yes
   ```

3. `ssh overmind-01` for a terminal, or in VS Code: install the **Remote - SSH**
   extension, then **Remote-SSH: Connect to Host...** → `overmind-01`. Open
   `/opt/overmind` until Substrate is mounted.
4. Before relying on it for git, verify the forwarded key actually reached the
   remote session: `ssh-add -l`, then `ssh -T git@github.com`.

Tailscale SSH is intentionally off; OpenSSH with the forwarded personal key is
the sole interactive auth path, matching
[git credentials](../../design-notes/security-model.md#git-credentials).

## Project ownership

Use a laptop IDE/SSH client to work on a project under `/mnt/substrate/projects`.
The project owns its source, documentation, temporary notes, data, and retained
outputs. It can be an independent Git checkout or a non-code collection.

Verify intended user/group permissions, project execution, and recovery of both
committed and uncommitted work once Substrate is mounted. Give concurrent agents
separate working copies and scoped execution. Do not sync live Git working
directories or databases indiscriminately between clients.

Shared notes under `/mnt/substrate/notes` may use a separate selected sync workflow.
Ordinary remote work and recovery must remain usable without Paperclip.
