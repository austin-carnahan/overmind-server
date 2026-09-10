# Tailscale

Status: planned private remote-access method; enrollment and policy are unverified.

Connect Overmind and selected clients through a private overlay. Do not expose
SSH, SMB, downloader RPC, or administrative interfaces through public forwarding.
Keep host access usable without Substrate; enrollment state belongs in native
protected service storage outside the collaborative surface.

Before deployment, verify the supported installation method, account/ACL policy,
DNS behavior, startup, and identity recovery/re-enrollment. Test client access
and ordinary LAN access. A separate DNS/subnet-router role is optional, not a
prerequisite. Outbound torrent privacy remains separate.
