#!/bin/bash
# MCP Profile Manager — switch between proxy and direct MCP connections
# Usage: mcp-profile <proxy|direct|status>

set -euo pipefail

CLAUDE_JSON="$HOME/.claude.json"
DIRECT_BACKUP="$HOME/.claude.json.direct-backup"
MCPPROXY="$HOME/.local/bin/mcpproxy"
PYTHON="$HOME/.local/bin/python3"

case "${1:-status}" in
    proxy)
        if ! pgrep -qf "mcpproxy serve"; then
            echo "⚠️  mcpproxy is not running. Start it first:"
            echo "  $PYTHON ~/workshop/scripts/workshop_services.py start mcpproxy"
            exit 1
        fi
        $PYTHON -c "
import json
with open('$CLAUDE_JSON') as f:
    cfg = json.load(f)
cfg['mcpServers'] = {'mcpproxy': {'url': 'http://127.0.0.1:8808/mcp'}}
with open('$CLAUDE_JSON', 'w') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
print('✅ Switched to proxy mode (http://127.0.0.1:8808/mcp)')
print('   Restart Claude Code sessions to apply.')
"
        ;;
    direct)
        if [[ ! -f "$DIRECT_BACKUP" ]]; then
            echo "❌ Direct backup not found at $DIRECT_BACKUP"
            exit 1
        fi
        cp "$DIRECT_BACKUP" "$CLAUDE_JSON"
        echo "✅ Switched to direct MCP connections (17 servers)"
        echo "   Restart Claude Code sessions to apply."
        ;;
    status)
        echo "=== MCP Profile Status ==="
        # Check which mode is active
        MODE=$($PYTHON -c "
import json
with open('$CLAUDE_JSON') as f:
    cfg = json.load(f)
servers = cfg.get('mcpServers', {})
if 'mcpproxy' in servers and 'url' in servers.get('mcpproxy', {}):
    print('proxy')
else:
    print(f'direct ({len(servers)} servers)')
")
        echo "Mode: $MODE"

        # Check proxy health
        if pgrep -qf "mcpproxy serve" 2>/dev/null; then
            HEALTH=$(curl -s http://127.0.0.1:8808/health 2>/dev/null || echo '{"status":"unreachable"}')
            echo "Proxy: running ($HEALTH)"
            # Count connected upstreams
            $MCPPROXY upstream list --json 2>/dev/null | $PYTHON -c "
import json, sys
data = json.load(sys.stdin)
connected = sum(1 for s in data if s.get('connected'))
total_tools = sum(s.get('tool_count', 0) for s in data)
print(f'Upstreams: {connected}/{len(data)} connected ({total_tools} tools)')
" 2>/dev/null || echo "Upstreams: unable to query"
        else
            echo "Proxy: not running"
        fi

        # Check backup exists
        if [[ -f "$DIRECT_BACKUP" ]]; then
            echo "Direct backup: ✅ available"
        else
            echo "Direct backup: ❌ missing"
        fi
        ;;
    *)
        echo "Usage: mcp-profile <proxy|direct|status>"
        echo ""
        echo "Commands:"
        echo "  proxy   — Use shared mcpproxy daemon (process reduction)"
        echo "  direct  — Use direct stdio connections (17 servers per session)"
        echo "  status  — Show current mode and proxy health"
        exit 1
        ;;
esac
