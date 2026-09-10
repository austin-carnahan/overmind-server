# Optional independent DNS host

Status: inherited future option; no hardware or deployment is assumed.

The prior plan proposed a Pi Zero 2 W for Pi-hole and optional private-network
routing. If retained, choose a supported OS/package setup, inspect router/DHCP
integration, and keep this host independent of media/compute/Substrate.

Record native state and configuration exports, then verify client resolution,
private administration, reboot, and recovery. Avoid inventing a static address
or enabling DHCP/DNS changes before the actual topology is known.
