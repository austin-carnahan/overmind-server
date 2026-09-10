# PIA / outbound privacy

Status: planned egress boundary for Transmission; no VPN installation verified.

Select a supported deployment method for the actual Pi/Ubuntu environment.
Scope private egress to the intended workload while retaining LAN/private-overlay
administration. Keep credentials in protected service configuration outside Git.

Before enabling unattended downloads, verify routed public address, DNS behavior,
VPN interruption/kill-switch behavior, restart ordering, and continued host
access. Document native state, health checks, rollback, and credential recovery.
Tailscale remote access and encrypted DNS do not replace this egress boundary.
