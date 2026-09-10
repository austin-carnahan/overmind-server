# Networking

**Status:** PROPOSED — see [status legend](README.md#status-legend); live topology and configuration are unverified.

Use the host pattern `overmind-01`, `overmind-02`, etc. Local DNS may use
`home.arpa`; example service names include `media.home.arpa`. Actual names and
addresses belong in the host's private configuration when sensitive.

Prefer DHCP reservations for infrastructure. Keep SSH and service administration
private through the LAN/private overlay. Tailscale is the current direction;
its enrollment and ACLs remain to be designed. Do not port-forward administration.

Outbound Transmission privacy is a separate VPN concern. Preserve management
access and test failure/kill-switch behavior before unattended downloads.
Encrypted DNS does not substitute for that egress boundary.

An optional separate Pi-hole/DNS host should remain independent of the compute
host. Exact router/DHCP/guest isolation topology must be inspected; old
Deco/BGW320 references are historical possibilities, not verified requirements.
