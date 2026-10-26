#!/usr/bin/env bash
# Connects the OpenClaw Gateway (this host) to Cerebrate MCP at
# 127.0.0.1:8002/mcp and scopes its tools to the agents in ALLOW_AGENTS.
# Run as a sudoer on overmind-01: bash openclaw-connect.sh
#
#   1. openclaw mcp add cerebrate (OpenClaw probes the server before saving)
#   2. tool policy, appended to what each agent already has (never replaced):
#        agents in ALLOW_AGENTS: "cerebrate__*" added to tools.alsoAllow when
#          the agent uses a tools.profile allowlist (Buckminster does)
#        every other agent: "cerebrate__*" added to tools.deny
#      shown, dry-run, then applied only after you confirm
#   3. restart the Gateway (mcp.* changes need a real restart), confirm a
#      new PID, and probe the server through OpenClaw
# Rollback: openclaw mcp unset cerebrate; remove "cerebrate__*" from the
# agents' tools lists; restart the Gateway.
set -euo pipefail

ALLOW_AGENTS=${ALLOW_AGENTS:-buckminster}
URL=http://127.0.0.1:8002/mcp

oc() { sudo -u openclaw bash -lc "cd && openclaw $*"; }

curl -s -f -m 10 http://127.0.0.1:8002/healthz >/dev/null || { echo "cerebrate-mcp isn't answering on 127.0.0.1:8002"; exit 1; }

if oc mcp show cerebrate >/dev/null 2>&1; then
  echo "== mcp.servers.cerebrate already configured"
else
  echo "== adding mcp.servers.cerebrate"
  oc mcp add cerebrate --transport streamable-http --url "$URL" --timeout 330
fi

echo "== tool policy"
agents_json=$(oc config get agents.list --json)
mapfile -t ops < <(ALLOW="$ALLOW_AGENTS" AGENTS="$agents_json" python3 - <<'EOF'
import json, os
allow = set(os.environ["ALLOW"].split())
for i, a in enumerate(json.loads(os.environ["AGENTS"])):
    tools = a.get("tools") or {}
    if a.get("id") in allow:
        if not tools.get("profile"):
            continue  # no allowlist profile: MCP tools are already visible to it
        key = "alsoAllow"
    else:
        key = "deny"
    cur = list(tools.get(key) or [])
    if "cerebrate__*" not in cur:
        print(f"agents.list[{i}].tools.{key}\t{json.dumps(cur + ['cerebrate__*'])}\t{a.get('id')}")
EOF
)
if [ ${#ops[@]} -eq 0 ]; then
  echo "nothing to change"
else
  for op in "${ops[@]}"; do
    IFS=$'\t' read -r path value id <<<"$op"
    echo "  $id: $path = $value"
    oc config set "'$path'" "'$value'" --strict-json --dry-run >/dev/null
  done
  read -r -p "Apply these ${#ops[@]} change(s)? [y/N] " answer
  [ "$answer" = y ] || { echo "not applied"; exit 1; }
  for op in "${ops[@]}"; do
    IFS=$'\t' read -r path value id <<<"$op"
    oc config set "'$path'" "'$value'" --strict-json
  done
fi

echo "== restarting the Gateway"
old_pid=$(systemctl show -p MainPID --value openclaw-gateway.service)
sudo systemctl restart openclaw-gateway.service
sleep 10
new_pid=$(systemctl show -p MainPID --value openclaw-gateway.service)
echo "Gateway PID $old_pid -> $new_pid ($(systemctl is-active openclaw-gateway.service))"
[ "$new_pid" != "$old_pid" ] && [ "$new_pid" != 0 ] || { echo "the Gateway did not restart cleanly"; exit 1; }

echo "== probe"
oc mcp probe cerebrate --json
