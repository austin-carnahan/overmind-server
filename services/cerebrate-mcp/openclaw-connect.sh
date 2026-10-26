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
# Every openclaw call's output is shown when it fails (a captured failure
# under set -e would otherwise exit silently).
# Agents are a map keyed by id: agents.entries.<id>.tools (OpenClaw 2026.9.6 schema).
if ! agents_out=$(oc config get agents.entries --json 2>&1); then
  echo "openclaw config get agents.entries --json failed:"; echo "$agents_out"; exit 1
fi
if ! ops_text=$(ALLOW="$ALLOW_AGENTS" AGENTS="$agents_out" python3 - <<'EOF'
import json, os, sys
allow = set(os.environ["ALLOW"].split())
text = os.environ["AGENTS"]
start = text.find("{")          # the CLI may print a banner before the JSON
try:
    agents, _ = json.JSONDecoder().raw_decode(text[start:]) if start >= 0 else (None, 0)
except ValueError:
    agents = None
if not isinstance(agents, dict) or not agents:
    sys.exit("could not read the agents from:\n" + text[:1500])
for agent_id, a in sorted(agents.items()):
    tools = (a or {}).get("tools") or {}
    if agent_id in allow:
        if not tools.get("profile"):
            continue  # no allowlist profile: MCP tools are already visible to it
        key = "alsoAllow"
    else:
        key = "deny"
    cur = list(tools.get(key) or [])
    if "cerebrate__*" not in cur:
        print(f"agents.entries.{agent_id}.tools.{key}\t{json.dumps(cur + ['cerebrate__*'])}\t{agent_id}")
EOF
); then
  exit 1
fi
ops=()
[ -n "$ops_text" ] && mapfile -t ops <<<"$ops_text"
if [ ${#ops[@]} -eq 0 ]; then
  echo "nothing to change"
else
  for op in "${ops[@]}"; do
    IFS=$'\t' read -r path value id <<<"$op"
    echo "  $id: $path = $value"
    if ! out=$(oc config set "'$path'" "'$value'" --strict-json --dry-run 2>&1); then
      echo "dry run failed for $path:"; echo "$out"; exit 1
    fi
  done
  read -r -p "Apply these ${#ops[@]} change(s)? [y/N] " answer
  [ "$answer" = y ] || { echo "not applied"; exit 1; }
  for op in "${ops[@]}"; do
    IFS=$'\t' read -r path value id <<<"$op"
    if ! out=$(oc config set "'$path'" "'$value'" --strict-json 2>&1); then
      echo "config set failed for $path:"; echo "$out"; exit 1
    fi
  done
  echo "applied"
fi

echo "== restarting the Gateway"
old_pid=$(systemctl show -p MainPID --value openclaw-gateway.service)
sudo systemctl restart openclaw-gateway.service
sleep 10
new_pid=$(systemctl show -p MainPID --value openclaw-gateway.service)
echo "Gateway PID $old_pid -> $new_pid ($(systemctl is-active openclaw-gateway.service))"
[ "$new_pid" != "$old_pid" ] && [ "$new_pid" != 0 ] || { echo "the Gateway did not restart cleanly"; exit 1; }

echo "== probe"
# Right after a restart the Gateway holds its state lock while it starts
# ("another OpenClaw process owns state-lifecycle"); retry for up to 2 minutes.
for attempt in $(seq 1 12); do
  if out=$(oc mcp probe cerebrate --json 2>&1); then echo "$out"; exit 0; fi
  echo "$out" | grep -q "state-lifecycle" || { echo "$out"; exit 1; }
  sleep 10
done
echo "$out"; exit 1
