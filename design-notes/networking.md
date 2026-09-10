# Networking

**Status:** PARTIAL — see [status legend](README.md#status-legend); Tailscale
enrollment for overmind-01 is verified below, remaining topology is unverified.

Use the host pattern `overmind-01`, `overmind-02`, etc. Local DNS may use
`home.arpa`; example service names include `media.home.arpa`. Actual names and
addresses belong in the host's private configuration when sensitive.

Prefer DHCP reservations for infrastructure. Keep SSH and service administration
private through the LAN/private overlay. Do not port-forward administration.

**Tailscale is enrolled.** overmind-01 joined via `tailscale up --hostname=overmind-01`;
MagicDNS is on, so any tailnet device reaches it as `overmind-01`. Node key
expiry is disabled for this host since it's an unattended server, not a laptop
that regularly re-authenticates. `ufw` is currently inactive on overmind-01, so
no additional firewall rule was needed for the `tailscale0` interface; revisit
if `ufw` is enabled later. ACLs remain the tailnet default (allow-all among
members) — adequate for one user and one server, revisit (e.g. tagging
overmind-01) once more devices or Paperclip agents join.

Interactive SSH auth uses plain OpenSSH with the client's forwarded agent key,
not Tailscale SSH — Tailscale SSH was deliberately left off
(`tailscale set --ssh=false`) so no private key material needs to live on the
host, matching the reasoning in [git credentials](security-model.md#git-credentials).
See [remote project work](../runbooks/clients/remote-work.md) for the connection
steps and VS Code setup.

Outbound Transmission privacy is a separate VPN concern. Preserve management
access and test failure/kill-switch behavior before unattended downloads.
Encrypted DNS does not substitute for that egress boundary.

An optional separate Pi-hole/DNS host should remain independent of the compute
host. Exact router/DHCP/guest isolation topology must be inspected; old
Deco/BGW320 references are historical possibilities, not verified requirements.
