# Deployment and Gateway

**Status:** PARTIAL — native install, systemd unit, and the real Tailscale
decision are verified; package-management/upgrade procedure is not yet
documented.

## Deployment architecture

OpenClaw runs **natively on the Overmind host** (`overmind-01`), not inside
Docker.

Reason: resident operator agents such as Kerrigan need legitimate access to
host administration, systemd, repositories, logs, and other machine-local
resources that a containerized Gateway would have to be given back through
bind mounts anyway.

```text
overmind-01
├── OpenClaw Gateway (native process, user: openclaw)
├── Docker/Podman application stack (unrelated services)
├── rootless Podman sandbox runtime (agent tool isolation)
└── agent workspaces: /home/openclaw/.openclaw/...
```

Installed via npm as the `openclaw` system user:
`/home/openclaw/.npm-global/bin/openclaw`. Version in use: `2026.9.6`.

Application workloads (Garmin MCP, media stack, etc.) remain containerized
independently of OpenClaw itself.

## Gateway and systemd

OpenClaw runs under a dedicated Unix system account: `openclaw`
(`useradd --system`, not an interactive login account).

The Gateway is a **system-level systemd unit**
(`/etc/systemd/system/openclaw-gateway.service`), not OpenClaw's own
user-systemd installer — this matters because a `useradd --system` account
doesn't get the lingering/user-session behavior a normal login user does by
default.

Verified real gotchas on this unit:

- needed an explicit `Environment=PATH=...` line — without it, the Gateway
  process didn't inherit a usable `PATH` and some subprocess spawns failed.
- `node` needed a scoped AppArmor profile
  (`/etc/apparmor.d/usr.bin.node`) to fix a startup `EACCES`:
  ```text
  abi <abi/4.0>,
  include <tunables/global>

  /usr/bin/node flags=(default_allow) {
    userns,
    include if exists <local/usr.bin.node>
  }
  ```
  `default_allow` plus an explicit `userns,` grant (user-namespace creation,
  needed for rootless Podman sandboxing — see
  [Sandboxing](sandboxing-and-trust.md#sandboxing)).

Restart with `sudo systemctl restart openclaw-gateway.service`, and always
confirm a **fresh PID** (`ps aux | grep openclaw-gateway`) before trusting a
config change is live — see
[Diagnostics and Quirks](diagnostics-and-quirks.md) for why this matters more
than the CLI's own "change will apply without restarting" messages suggest.

## Remote access and Tailscale

`gateway.bind: "loopback"` — the Gateway never listens on anything but
`127.0.0.1`.

**Real decision, not the obvious default:** we did *not* turn on OpenClaw's
own managed `gateway.tailscale.mode: "serve"`. This host already had an
externally-managed Tailscale Serve route (`tailscale serve`, run manually,
pre-dating OpenClaw's own management) bound to HTTPS port `18789` →
`127.0.0.1:18789`, used for the Control UI dashboard. Turning on OpenClaw's
managed mode would try to claim the Gateway's HTTPS route and risked
colliding with an *unrelated* existing Funnel route already occupying the
default HTTPS port 443 for another service on this host. We left
`gateway.tailscale.mode: "off"` and kept the manual route.

Mobile app pairing (`openclaw qr` / Control UI "Pair device") only advertises
a Tailscale setup URL when OpenClaw itself owns the Serve/Funnel route
(`gateway.tailscale.mode=serve|funnel`) — an externally-managed route is
*not* auto-advertised. Since we deliberately kept external management, the
fix was the other documented escape hatch:

```text
plugins.entries.device-pair.config.publicUrl
  → "wss://overmind-01.<tailnet>.ts.net:18789"
```

matching the already-working manual Serve route. No Tailscale operator grant
was needed for this path (that would only matter if OpenClaw itself were
calling `tailscale serve` as the `openclaw` Unix user).

```text
Gateway (127.0.0.1:18789)
    ↓
externally-managed `tailscale serve` (HTTPS :18789, tailnet-only)
    ↓
device-pair publicUrl override → mobile app setup codes
```

Tailnet: MagicDNS + HTTPS cert enabled (both required prerequisites for
Serve/Funnel).

## Permissions and host administration

Kerrigan's design principle: **broad operational jurisdiction, narrow
standing privilege, wide task-scoped authority.**

Real grants on `overmind-01`:

- `/etc/sudoers.d/openclaw-observe` — read-only Docker inspection, scoped.
- `/etc/sudoers.d/austin-openclaw-impersonate` —
  `austin ALL=(openclaw) NOPASSWD: ALL`. This lets the human operator (and an
  assistant acting on their behalf) become the `openclaw` user without a
  password — but it is **impersonation only**, not general root. Austin's own
  general sudo (`(ALL:ALL) ALL`) still requires an interactive TTY password,
  so any genuinely root-level action (systemctl restarts of *other* services,
  package installs, sudoers/AppArmor file edits) has to be run by the human
  directly, not scripted by an assistant through this grant.
- `systemd-journal` group membership for `openclaw` — read-only log access
  without broader privilege.
- rootless Podman, not Docker-group membership, for sandbox isolation (see
  [Sandboxing](sandboxing-and-trust.md#sandboxing)) — a deliberate choice to
  avoid giving `openclaw` root-equivalent access via `docker.sock`.

Prefer native OS mechanisms over a bespoke capability layer:

```text
filesystem        → Unix ownership/groups/ACLs
journals          → systemd-journal group
systemd           → native systemd / polkit
privileged OS ops → sudo, scoped per-action, never blanket
Docker            → treat daemon socket access as root-equivalent
```

`gateway.auth.token` is stored as a SecretRef (`GATEWAY_AUTH_TOKEN` in the
Gateway's own SQLite secrets store), not plaintext config.
`gateway.trustedProxies: ["127.0.0.1"]` is set for the loopback proxy path.

OpenClaw's own tool-approval layer and OS-level privilege escalation are
separate concerns — granting a tool policy allowance never substitutes for an
actual sudoers/AppArmor grant, and vice versa.
