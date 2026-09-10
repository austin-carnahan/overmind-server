# Pi-hole

Status: optional future DNS role; no separate DNS host is confirmed.

The prior design suggested a Pi Zero 2 W for DNS filtering, local `home.arpa`
records, and an encrypted upstream resolver. Keep such a host independent of
Overmind's media/compute and optional Substrate.

Before implementation, inspect router/DHCP topology, choose supported software,
record identity and native state, then test client resolution and recovery.
Maintain DNS configuration exports separately from media libraries. See the
[optional DNS host runbook](../../runbooks/clients/optional-dns-host.md).
