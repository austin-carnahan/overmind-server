# Home DNS + reverse-proxy plan: readable names for LAN and Tailscale

**Status:** PARTIAL — see [status legend](README.md#status-legend); Stages 1
and 2 are executed and verified live (DNS rewrites + reconciliation tooling,
Caddy on both Cerebrate and Overmind). Stage 3 (AT&T gateway route, HTTPS
follow-up) remains PROPOSED — see the staging note added after each phase
below for exactly what's done vs. still ahead.

## Current state (as given, some still to verify in Phase 0)

- `cerebrate-pi0` runs AdGuard Home at `192.168.68.59`, on the home tailnet.
- `home.arpa` is a Tailscale split-DNS domain pointed at Cerebrate.
- Cerebrate advertises the LAN subnet `192.168.68.0/22` as a Tailscale subnet router.
- `cerebrate-pi0.home.arpa` and `overmind.home.arpa` already resolve correctly.
- Overmind has a reserved LAN address (exact value: verify in Phase 0 — not
  yet recorded in this repo).
- AdGuard and every Overmind service currently use explicit, non-standard
  ports (see the port table below).
- No `hosts/cerebrate-pi0/` doc exists in this repo yet — Cerebrate has been
  set up outside this repo's tracked history so far.

## Design principles (restated from the request, kept as the constraint set)

1. DNS naming is network-wide, owned by AdGuard Home.
2. Physical hosts and the services running on them may have different names.
3. A service's DNS name points at the machine actually hosting it.
4. Reverse proxying is host-local, not centralized through Overmind.
5. Overmind proxies only what Overmind hosts; Cerebrate proxies only what
   Cerebrate hosts.
6. Devices we don't control (Deco, AT&T gateway) get direct DNS names, not
   proxying, wherever possible.
7. Pretty names must keep working off-LAN via existing split-DNS + subnet
   routing — no new Tailscale mechanism required for the common case.
8. Overmind going down must not take down Cerebrate, AdGuard, or core network
   name resolution. (Note: AdGuard itself going down *does* take down all
   `home.arpa` resolution, Cerebrate included — that's an existing
   single point of failure this plan doesn't remove, only avoids making
   worse. See "Second AdGuard node" and "Security considerations" below.)

## Known service ports on Overmind (source: `services/*/compose.yaml`, current `docker ps`)

| Service | Port | Notes |
| --- | --- | --- |
| Jellyfin | 8096 | |
| Transmission (via gluetun) | 9091 | gluetun container publishes this |
| Radarr | 7878 | |
| Sonarr | 8989 | |
| Bazarr | 6767 | |
| Prowlarr | 9696 | |
| ROMarr | 6868 | |
| Seerr | 5055 | |
| Maintainerr | 6246 | |
| Cloudflare-solver | 8000 | internal use by Prowlarr; likely not worth a public name |
| Samba | 445/139 | SMB, not HTTP — not a reverse-proxy candidate |
| Paperclip | 127.0.0.1:3100 | already loopback-only; not exposed, no DNS name needed |

AdGuard's own admin-UI port on Cerebrate is unverified — commonly `3000`
(first-run) or reassigned to `80` during setup. This matters because Caddy on
Cerebrate needs port `80` (and later `443`) free; if AdGuard already owns
`80`, it must be moved first (Phase 0).

---

## Phase 0 — Verify before touching anything

Nothing here changes state; it establishes ground truth so later steps use
real values instead of assumptions.

1. SSH to `cerebrate-pi0` and confirm:
   - AdGuard Home's actual admin-UI bind address/port
     (`AdGuardHome.yaml` → `http.address`).
   - Whether AdGuard runs natively (systemd) or in a container.
   - Whether anything already listens on `80`/`443`.
2. Confirm Overmind's reserved LAN IP (DHCP reservation or static config) and
   record it in a new `hosts/cerebrate-pi0/README.md` and an update to
   `hosts/overmind-01/README.md`, matching this repo's existing per-host
   inventory convention.
3. From a LAN client, determine the AT&T BGW320's actual management IP and
   whether it's inside or outside `192.168.68.0/22`. If outside, determine
   whether it's already reachable from LAN clients today (many ISP
   gateway+mesh combos still allow direct LAN access to the gateway even in
   passthrough/bridge mode) — if so, no new Tailscale route may be needed at
   all for LAN use, only for off-LAN admin access.
4. Confirm the Deco's management IP and whether it already falls inside the
   advertised `/22`. (Done — `192.168.68.1`, inside the `/22`, but it has no
   browsable web interface at all; TP-Link Deco is app-managed only. No
   `deco.home.arpa` entry added as a result — nothing to point it at.)
5. Confirm AdGuard Home's "DNS rebinding protection" setting doesn't need an
   explicit allowlist for private-IP rewrites (it's usually fine for
   RFC1918 targets, but verify rather than assume once rewrites are added).

---

## Naming convention: node / convenience alias / service

Adopted during Stage 1 execution, verified live before committing to it
(AdGuard Home resolves a rewrite whose `target` is another hostname as a
real CNAME chain, confirmed with `dig` against the live instance — not just
accepted syntax that silently fails). Three tiers, all still directly under
`home.arpa`:

- **Node** — an actual machine, name matches its real hostname
  (`cerebrate-pi0.home.arpa`, `overmind-01.home.arpa`). The *only* tier
  where a raw IP appears. Answers "which computer am I talking to?"
  "Cerebrate" is a fleet/class name for small auxiliary compute nodes
  (`cerebrate-pi0` today, future `cerebrate-pixel3`/`cerebrate-pixel6`,
  etc.) — a family of devices, not a DNS role.
- **Convenience alias** — shorthand for "the current primary machine for
  this job," created *only* where there's one unambiguous singleton.
  `overmind.home.arpa` → `overmind-01.home.arpa` qualifies today (exactly
  one canonical Overmind server). There's deliberately no
  `cerebrate.home.arpa`: once the fleet has more than one heterogeneous
  member, "the Cerebrate" has no single obvious answer, so it doesn't get
  an alias — a family name describes devices, a service name describes
  capabilities, and a generic family alias only exists when there's
  actually one obvious canonical member to point it at.
- **Service** — a capability, independent of whichever node hosts it today
  (`adguard.home.arpa`, `jellyfin.home.arpa`, a future `inference.home.arpa`
  pointing at whichever accelerator node hosts it that month, ...). Also
  points at a node name, not an IP.

The payoff: IPs live in exactly one place (node records). Swapping hardware
— e.g. AdGuard eventually moving to a `cerebrate-pixel3` node — means
editing one node record or one service target, never every consumer of
that service's name. See `hosts/dns-rewrites.yaml` for the current, real
file.

---

## Phase 1 — DNS rewrites in AdGuard Home

Use AdGuard Home's **DNS rewrites** (Filters → DNS rewrites), not a full
zone file — it's the right-sized tool for ~15 static name→IP mappings and
needs no separate DNS server software.

Records (finalized after Phase 0, restructured into the node/role/service
tiers above — see `hosts/dns-rewrites.yaml`, the actual source of truth;
this table is illustrative, not re-maintained separately):

| Name | Tier | Target | Rationale |
| --- | --- | --- | --- |
| `cerebrate-pi0.home.arpa` | node | `192.168.68.59` | real hostname; pre-existing entry, now brought under management |
| `overmind-01.home.arpa` | node | `192.168.68.55` | real hostname; Overmind's reserved wired (eth0) address |
| `overmind.home.arpa` | alias | `overmind-01.home.arpa` | convenience alias; previously pointed straight at `.50` (wlan0). No `cerebrate.home.arpa` equivalent — see naming convention above |
| `adguard.home.arpa` | service | `cerebrate-pi0.home.arpa` | proxied by Cerebrate's own Caddy |
| `transmission.home.arpa` | service | `overmind-01.home.arpa` | proxied by Overmind's Caddy |
| `jellyfin.home.arpa` | service | `overmind-01.home.arpa` | " |
| `radarr.home.arpa` | service | `overmind-01.home.arpa` | " |
| `sonarr.home.arpa` | service | `overmind-01.home.arpa` | " |
| `bazarr.home.arpa` | service | `overmind-01.home.arpa` | " |
| `prowlarr.home.arpa` | service | `overmind-01.home.arpa` | " |
| `romarr.home.arpa` | service | `overmind-01.home.arpa` | " |
| `seerr.home.arpa` | service | `overmind-01.home.arpa` | " |
| `maintainerr.home.arpa` | service | `overmind-01.home.arpa` | " |
| `bgw320.home.arpa` | (device, not ours) | `192.168.1.254` | direct IP, no proxy — AT&T gateway, passthrough behind the Deco |

No entry for the Deco itself: its management IP (`192.168.68.1`, the LAN
default gateway) has no browsable web interface — it's app-managed only
(TP-Link Deco app). Nothing to point a name at unless that changes.

Not proposed: a name for `cloudflare-solver` (internal-only, consumed by
Prowlarr, no human-facing reason to browse it) or `samba` (SMB isn't
browser/HTTP traffic — clients already connect by IP or existing name, a
`home.arpa` name is optional polish, not part of this plan's scope).

Each name resolves straight to the *host* IP (per principle 3), and Caddy on
that host is what actually disambiguates which service a given hostname
means — AdGuard never needs to know about ports.

### Canonical source + reconciliation script (git-tracked map, pushed via API)

Rather than editing AdGuard's UI as the source of truth, the rewrite table
above lives as a git-tracked file, and a small idempotent script reconciles
AdGuard's live state to match it. AdGuard's live config becomes a *cache* of
this file, not the canonical copy — same "canonical state should be boring"
principle the Substrate notes elsewhere in this repo already settled on.

**File**: `hosts/dns-rewrites.yaml`

See `hosts/dns-rewrites.yaml` for the actual, current file — kept in one
place rather than duplicated here to avoid the two drifting apart.

**Script**: `scripts/sync-dns-rewrites` (or a short Python script if the
diffing logic gets awkward in bash — either is fine, no framework needed).

For each node in `nodes`:

1. `GET /control/rewrite/list` — the node's current live rewrites.
2. Diff against `hosts/dns-rewrites.yaml`'s `rewrites` list:
   - **Missing on the node** → `POST /control/rewrite/add`.
   - **Present on the node with a different target than the file** →
     AdGuard's API has no in-place update, so this is
     `POST /control/rewrite/delete` (old value) then `add` (new value).
   - **Present on the node but absent from the file** → flag for removal,
     see the ownership guard below.
   - **Matches already** → no-op (this is what makes repeated runs safe).
3. Print a plan (what will be added/changed/removed) and require `--apply`
   to actually call the mutating endpoints — default to dry-run so this is
   safe to run ad hoc or from a cron/systemd timer without surprises.

**Ownership guard, so this doesn't clobber unrelated manual entries**: only
ever delete/modify a rewrite whose name is `*.home.arpa` and was previously
written by this script (track applied state in a small
`hosts/.dns-rewrites.state.json`, git-ignored, written after each successful
apply). A rewrite that exists on the node but was never in that state file is
left alone and just reported, not deleted — protects against the script
being run before every name is captured in the YAML, or against someone
adding a one-off rewrite by hand later.

**Credentials**: AdGuard's API needs its admin username/password (session
cookie or basic auth depending on version) — keep these in an untracked
`.env`/`hosts/dns-sync.env` alongside the script, following this repo's
existing convention of committing `.env.example` only.

This solves three things at once:

- **Reproducibility/backup**: the map lives in git; a fresh AdGuard install
  (or the future second node) is one script run away from the correct
  state, not a manual UI re-entry job.
- **Second AdGuard node**: covered by construction — it's just another
  entry in `nodes`, reconciled by the same run.
- **Drift detection**: the dry-run diff doubles as a "what changed since
  last sync" check — run it (without `--apply`) any time as a sanity check
  that AdGuard's live state still matches the repo.

Also back up `/opt/AdGuardHome/AdGuardHome.yaml` (or wherever Cerebrate's
install keeps it) into whatever backup destination the repo's restic/B2
strategy already covers for Overmind — extend that scope to Cerebrate rather
than inventing a second backup mechanism. The git-tracked rewrite map doesn't
replace this: it recreates the *rewrite list* specifically, not AdGuard's
full config (filtering lists, client settings, etc.).

---

## Phase 2 — Host-local Caddy on Cerebrate — DONE (2026-09-16)

Executed as planned: native Caddy `2.11.4` install via the official
`.deb` (arm64), downloaded from GitHub releases and verified against the
published **SHA-512** checksums file before installing (note: that file
uses SHA-512, not SHA-256, despite the generic filename — worth a second
look if verifying a future release the same way). AdGuard's admin port
(`3000`) needed no change; nothing else was on `80`.

Live config: `hosts/cerebrate-pi0/Caddyfile` (deployed to
`/etc/caddy/Caddyfile`). No site block for a `cerebrate.home.arpa` alias
since the naming-convention decision above dropped it — see that section.

Real gotcha hit during this step, worth keeping: Caddy's automatic HTTPS
kicks in by default for anything that looks like a real domain — even
`.home.arpa` — adding an ACME attempt and an HTTP→HTTPS redirect neither of
which we want (Phase 4 chose HTTP-only deliberately). Fixed by prefixing
each site address with the `http://` scheme, which disables automatic HTTPS
for that site specifically:

```caddyfile
http://adguard.home.arpa {
	reverse_proxy 127.0.0.1:3000
}
```

Verified: `curl -H "Host: adguard.home.arpa" http://127.0.0.1/` and
`curl http://adguard.home.arpa/` (from the LAN) both return AdGuard's own
302 to `/login.html`, proxied correctly (`Via: 1.1 Caddy` in the response).

## Phase 3 — Host-local Caddy on Overmind — DONE (2026-09-16)

Executed as planned: Caddy added as `services/caddy/compose.yaml` in the
`services/compose.yaml` `include:` list, joining `services_default` with no
explicit `networks:` override — same pattern every other fragment here
uses, so it resolves `jellyfin`, `radarr`, etc. by container name without
hitting the isolated-network bug. Image pinned to
`caddy:2.11.4@sha256:1172d4213087d3fc30bafc7ff2c2896180eb0c41ff7f75f315568fb36cabdcba`
(arm64 manifest digest, resolved against Docker Hub same day). No
`cap_drop: ALL` on this one service specifically — Caddy runs as root in
its own image and needs `CAP_NET_BIND_SERVICE` to bind port `80`; dropping
all capabilities would break that even for root. See
`services/caddy/compose.yaml` and `services/caddy/Caddyfile` for the live
files.

Real gotcha hit here, distinct from the Cerebrate one: a Caddyfile with
each site written as a single line (`name.home.arpa { reverse_proxy ... }`
all on one line) failed to parse — `Unexpected '}' because no matching
opening brace` on the very first block, even though the braces were
genuinely balanced. Multi-line form (address, then `{`, then the directive
indented on its own line, then `}`) parsed and worked correctly:

```caddyfile
http://jellyfin.home.arpa {
	reverse_proxy jellyfin:8096
}
```

Same `http://` scheme prefix as Cerebrate, same reason (disable automatic
HTTPS). `overmind.home.arpa` itself still gets no site block — no cosmetic
landing page was added, matching the "not required for this plan's goal"
call from the original draft.

Verified: `curl -o /dev/null -w '%{http_code}' http://<name>.home.arpa/`
for every service returned each app's own real response code (200/301/302
depending on the app's default unauthenticated behavior), never a
connection failure or a 502 — confirming Caddy is actually reaching each
backend by container name, not just accepting the config.

Existing explicit ports (`:9091`, `:8096`, etc.) keep working unchanged
throughout — Caddy is additive, nothing is being removed from
`compose.yaml` or renumbered. That also means every step here is
individually safe to test without breaking current access.

---

## Phase 4 — HTTP now, defer HTTPS

Recommendation: **HTTP only for now**, matching the reasoning already applied
to Jellyfin/Seerr in this project — Tailscale's WireGuard tunnel is the real
transport-security boundary for off-LAN access, and LAN traffic never leaves
a network you control. Nothing here is port-forwarded or Internet-reachable,
so plaintext HTTP inside that boundary isn't a new exposure versus today's
direct-port access.

If trusted HTTPS is wanted later: **`home.arpa` cannot get a publicly-trusted
certificate** — `.arpa` is an IANA special-use TLD, not something any public
CA can domain-validate. The workable path is a **private subdomain of a real
owned domain** (e.g. `lan.<yourdomain>`) using Let's Encrypt's **DNS-01**
challenge: DNS-01 only requires the ability to create a TXT record on that
domain's *public* authoritative DNS — it does not require the A/AAAA record
itself to ever resolve publicly. So the internal names can keep resolving
only via AdGuard's split-DNS to private IPs, while still getting real,
browser-trusted certificates. This is a well-established pattern (Caddy and
most ACME clients support DNS-01 directly), not something to build custom
tooling for — worth a dedicated follow-up plan if/when pursued, not bundled
into this one.

---

## Phase 5 — Tailscale routing for the AT&T gateway (conditional)

Only needed if Phase 0 finds the BGW320's management IP is **not** already
reachable from LAN clients and is outside the advertised `192.168.68.0/22`.

If so: advertise the narrowest correct additional route from Cerebrate (or
whichever host can reach it) —

```bash
sudo tailscale up --advertise-routes=192.168.68.0/22,<gateway-subnet-or-/32>
```

prefer the gateway's real subnet if it's a defined `/24`; fall back to a
single `/32` only if the gateway is genuinely the only device reachable
there. Approve the new route in the Tailscale admin console (routes don't
take effect until approved, same as the existing `/22`). This is additive to
the existing route advertisement, not a replacement.

---

## Verification

**LAN:**
- `dig <name>.home.arpa @192.168.68.59` for every name in the Phase 1 table
  — confirm each resolves to the intended IP.
- `curl -I http://<name>.home.arpa/` for every proxied service from a LAN
  client — confirm Caddy answers and proxies to the right backend (compare
  response against `curl -I http://<host-ip>:<port>/` direct-port baseline).

Real gotcha hit at this step, client-side rather than server-side: a
browser (Brave, Chromium-based) failed with `ERR_ADDRESS_UNREACHABLE` on
every `*.home.arpa` name while `dig` and `curl` from the *same Mac*, at the
same time, resolved and connected correctly. Root cause was macOS's Local
Network privacy permission (Settings → Privacy & Security → Local Network)
— it gates an app's ability to reach RFC1918 addresses per-app, separate
from any DNS/routing/firewall config, and CLI tools aren't sandboxed the
same way a browser is. Not a Tailscale, DNS, or Caddy issue at all, despite
initially looking like one (routing-error-shaped symptom). Grant the
browser Local Network access and retest before suspecting anything
server-side for this exact symptom.

**Off-LAN (Tailscale, physically off the home LAN):**
- From a device connected to the tailnet but not on `192.168.68.0/22`
  (cellular data, different network), confirm `home.arpa` names still
  resolve — this exercises Tailscale split-DNS forwarding to Cerebrate.
- Confirm the resolved private IPs are actually reachable — this exercises
  the subnet-router path, separate from DNS.
- Repeat the same `curl -I` checks as the LAN pass.

**Failure isolation (validates principle 8):**
- Stop Overmind's `services` stack (or the whole host) and confirm
  `cerebrate-pi0.home.arpa` / `adguard.home.arpa` still resolve and respond —
  proves Overmind's failure doesn't take down Cerebrate or core DNS.
- Note the converse is *not* true and isn't fixed by this plan: if Cerebrate
  or AdGuard goes down, all `home.arpa` resolution fails, Overmind's own
  services included, since AdGuard is the only resolver for that zone right
  now. That's the argument for eventually standing up the second AdGuard
  node already mentioned in `services/pihole/README.md`'s history — out of
  scope for this plan, but worth flagging as the actual mitigation when it
  happens.

## Rollback

Every change here is additive and non-destructive to what exists today:

- DNS rewrites: `git revert` the change to `hosts/dns-rewrites.yaml` and
  re-run `scripts/sync-dns-rewrites --apply` — the reconciliation script
  removes whatever it previously added that's no longer in the file (subject
  to the ownership guard above). The original `cerebrate-pi0.home.arpa` and
  `overmind.home.arpa` records are untouched throughout, since they were
  never managed by this script.
- Caddy on either host: stop/remove the container (Overmind) or service
  (Cerebrate) — every backend service keeps answering on its original
  explicit port throughout, since nothing about the underlying services
  changes. There is no cutover moment where the old access path stops
  working, which also means testing can happen incrementally without any
  user-facing downtime.
- AT&T gateway route (if added): remove the advertised route and disable it
  in the Tailscale admin console.

## Security considerations

- No new port-forwarding anywhere — Caddy only listens on LAN-private
  interfaces, reachable via LAN or the existing Tailscale subnet route,
  matching every other service's existing "Tailscale-only, never exposed"
  posture in this repo.
- Caddy's own admin API (`:2019` by default) should stay bound to localhost
  or be disabled — it's unauthenticated by default and shouldn't be reachable
  from the LAN/tailnet.
- AdGuard's own login stays enforced behind Caddy; the proxy doesn't change
  or need to duplicate its auth.
- Verify AdGuard's DNS-rebinding protection doesn't silently drop the new
  private-IP rewrites (Phase 0) — a subtle failure mode where DNS resolves
  from AdGuard's own admin UI test tool but not from actual clients.
- HTTP-only (Phase 4) is a deliberate, revisitable choice, not an oversight
  — consistent with how Jellyfin/Seerr's transport security was already
  reasoned about earlier in this project: Tailscale is the encryption
  boundary, not the app layer, for anything not port-forwarded.

## Open items for a future pass (explicitly out of scope here)

- A `hosts/cerebrate-pi0/README.md` matching `hosts/overmind-01/README.md`'s
  inventory format.
- The second AdGuard node's own host inventory and deployment.
- Actually pursuing Phase 4's HTTPS follow-up, if/when trusted certs become
  worth the added moving parts.
