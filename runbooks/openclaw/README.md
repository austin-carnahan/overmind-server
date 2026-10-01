# OpenClaw on Overmind

**Status:** PARTIAL — core deployment, sandboxing, mobile trust, and MCP
findings below are verified on the live `overmind-01` host; some subsections
(marked) are still placeholders for detail we haven't needed yet.

> OpenClaw changes quickly. Treat the live installed version
> (`openclaw --version`), `openclaw config schema`, and current upstream docs
> as authoritative when implementation details here conflict with them.

This is the canonical index for how OpenClaw is deployed and operated on
Overmind. It replaces the single draft doc
(`design-notes/OpenClaw on Overmind — Runbooks.md`), split by how often each
part actually changes:

- [Deployment and Gateway](deployment-and-gateway.md) — native install,
  systemd, Tailscale/remote access, host permissions. Rarely revisited.
- [Agents and Model Routing](agents-and-model-routing.md) — per-agent
  workspace files, model/reasoning-effort config, persistent agent state.
- [Sandboxing and Trust](sandboxing-and-trust.md) — the session trust model,
  sandbox config, Android/mobile sessions, MCP tool access, subagent
  repository access. The dense, fastest-moving part — most of what we've
  learned operating Kerrigan and Soma lives here.
- [Diagnostics and Quirks](diagnostics-and-quirks.md) — first-line commands,
  known quirks, dated change log. Meant to keep growing; append here rather
  than letting the architecture docs above turn into a log.

## Maintenance rule

When OpenClaw behavior surprises us:

1. reproduce the issue;
2. inspect effective runtime/session state (not just config);
3. verify against current upstream docs/source, not memory of how it used
   to work;
4. make the narrowest supported change;
5. verify boundaries after the change (what's still sandboxed, what isn't,
   what other agents did *not* get touched);
6. add the durable lesson to [Diagnostics and Quirks](diagnostics-and-quirks.md).

These documents are an index of how *we* operate OpenClaw on Overmind, not a
substitute for upstream documentation.
