# Contributing

Read [AGENTS.md](AGENTS.md) and [the design index](design-notes/README.md).

1. Document a proposed behavior or ownership change before implementing it.
2. Prefer supported tools and small idempotent operations over a custom platform.
3. Keep examples nonsecret and clearly distinguish planned from tested behavior.
4. Add verification and rollback/recovery instructions for deployed capabilities.
5. Run `./scripts/check-repo`. CI additionally requires ShellCheck.

Host installation, filesystem changes, and service deployments are separate
from editing this scaffold. Do not run example fragments against a real host
without resolving the prerequisites in that host/service's documentation.
Historical discussion is retained for provenance; current design documents and
explicit user decisions supersede it.
