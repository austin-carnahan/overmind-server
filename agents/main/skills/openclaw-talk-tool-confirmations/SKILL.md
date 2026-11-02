---
name: openclaw-talk-tool-confirmations
description: Explain or troubleshoot exact-action tool confirmations during OpenClaw browser Talk, including read-only work wrapped in high-impact tools.
---

# Browser Talk tool confirmations

Use when a Talk user asks why an action needs repeated approval or how to exempt simple lookups.

1. Check the current Talk confirmation docs (`docs/nodes/talk/realtime-sessions.md` and `docs/gateway/protocol/rpc-talk-config-and-agents.md`). Voice-originated high-impact actions require a **later finalized, saved user utterance** confirming the exact final arguments; approval is consumed once. A changed action or policy rewrite requires a new confirmation. Do not infer that a spoken `yes` approved a tool unless its retry actually ran.
2. A read-only lookup made through the Code Mode `exec` wrapper can still be gated as `exec`. Explain the exact pending action; after confirmation retry only that exact call, and distinguish a new `VOICE_CONFIRMATION_REQUIRED` from a completed result. Avoid chaining unrelated tool calls under one confirmation or promising that a quick search is exempt.
3. For requests to reduce prompts, inspect the current documented schema/policy via OpenClaw setup tooling. In the inspected 2026.9.6 configuration, there was **no supported key to exempt read-only actions from Talk's high-impact gate**; `approvals.exec` forwarding is not an exemption. Do not invent a toggle, silently disable safeguards, or edit Gateway configuration outside the supported control path. Report the actual blocker and whether any setting changed.
