# MCP Optimization Blueprint

> **Status**: ✅ COMPLETED — Layer 0 + Layer 1b (2026-03-15)
> **Outcome**: mcpproxy-go v0.20.2 部署完成，72+ processes → ~20 shared；mcp-profile.sh 可切換 profile；Layer 1a (semantic filter) 與 Layer 2 (long-term) 保留為未來選項
>
> _Original problem: 4+ Claude Code sessions x 17 MCP servers = 72+ processes_
> _22 MCP servers exist in `mcp/`, 153 total tools; Claude Code loads 17 servers (~116 tools)_
> _Goal: Reduce process count 4-10x while maintaining full tool access_

---

## Layer 0: Immediate — mcpproxy-go Adoption

### 0a. Architecture

```
Before (per session):
  Claude Code ──stdio──> memvault server.py      (python3 process)
               ──stdio──> finance server.py       (uv + python3)
               ──stdio──> capture server.py       (uv + python3)
               ──stdio──> ... x17 servers
  = 17-30 processes per session, 72+ across 4 sessions

After:
  Claude Code ──stdio──> mcpproxy serve (1 Go binary, stdio mode)
                           ├──stdio──> memvault server.py
                           ├──stdio──> finance server.py
                           ├──stdio──> ... x17 upstream servers
                           └──http──> deepwiki (remote)
  = 1 mcpproxy + 17 upstream = 18 shared processes for ALL sessions
```

Key insight: mcpproxy maintains **one set** of upstream connections, shared across
all Claude Code sessions connecting to it. This turns O(sessions x servers) into O(servers).

### 0b. `~/.claude.json` Change

Replace all 17 `mcpServers` entries with a single proxy entry:

```json
{
  "mcpServers": {
    "mcpproxy": {
      "command": "/Users/joneshong/.local/bin/mcpproxy",
      "args": ["serve", "--log-to-file"],
      "env": {}
    }
  }
}
```

Claude Code connects to mcpproxy via stdio. The proxy reads its config from
`~/.mcpproxy/mcp_config.json` (already configured with all 17 servers).

**BM25 tool filtering**: With `top_k: 10` configured, mcpproxy returns only the
10 most relevant tools per `tools/list` call, reducing the tool descriptions
sent to the model from ~116 to ~10. This saves significant context tokens.

### 0c. mcpproxy Config Adjustments (`~/.mcpproxy/mcp_config.json`)

Current config is already good. Required changes:

```jsonc
{
  "listen": "127.0.0.1:8808",       // keep for Web UI access
  "enable_web_ui": true,             // keep — monitoring dashboard
  "enable_socket": true,             // keep — IPC for CLI commands
  "top_k": 10,                       // BM25 filter: 10 most relevant per query
  "tools_limit": 200,                // hard cap (153 total, safe margin)
  "tool_response_limit": 20000,      // truncate oversized responses (match our MCP convention)
  // Add missing servers not yet in mcpproxy:
  // intelflow, nodeflow, finance-analytics, finance-wallet, sentinel,
  // system-monitor, envkit, tmux-webui (8 servers)
}
```

**Action**: Run `mcpproxy upstream add-json` for the 8 missing servers to have
full parity (22 servers in proxy vs 17 currently in claude.json).

### 0d. Integration with workshop_services.py

Register mcpproxy as a managed service:

```python
# In scripts/workshop_services.py SERVICES list:
{
    "name": "mcpproxy",
    "type": "binary",
    "cmd": "/Users/joneshong/.local/bin/mcpproxy serve --listen 127.0.0.1:8808 --log-to-file",
    "port": 8808,
    "health": "http://127.0.0.1:8808/health",
    "workdir": "/Users/joneshong",
},
```

This gives mcpproxy:
- Auto-start on boot (via launchd daemon mode)
- Health monitoring (60s interval)
- Auto-restart on crash
- Log rotation
- PID tracking

### 0e. Sentinel Integration

```python
# In stations/sentinel/checker.py LIGHT_CHECKS:
LightCheck(
    name="mcpproxy",
    group="infra",
    url="http://127.0.0.1:8808/health",
),

# In stations/sentinel/remediation.py SIMPLE_RESTART_MAP:
"mcpproxy": "mcpproxy",
```

### 0f. Fallback Strategy

If mcpproxy fails to start or crashes:

1. **Automatic**: workshop_services.py daemon restarts it within 60s
2. **Manual**: `~/.local/bin/python3 ~/workshop/scripts/workshop_services.py restart mcpproxy`
3. **Emergency**: Swap `~/.claude.json` back to direct connections

Fallback script (`scripts/mcp-profile.sh` — see Layer 1b):
```bash
# Emergency: revert to direct connections
workshop mcp-profile direct
```

### 0g. Implementation Checklist

| # | Task | File | Est. |
|---|------|------|------|
| 1 | Add 8 missing servers to mcpproxy config | `~/.mcpproxy/mcp_config.json` | 15min |
| 2 | Test mcpproxy serve with all 22 upstreams | manual | 30min |
| 3 | Replace claude.json mcpServers with single proxy | `~/.claude.json` | 5min |
| 4 | Register in workshop_services.py | `scripts/workshop_services.py` | 10min |
| 5 | Add sentinel light check | `stations/sentinel/checker.py` | 5min |
| 6 | Add remediation mapping | `stations/sentinel/remediation.py` | 5min |
| 7 | Verify: open 2+ sessions, confirm shared processes | manual | 15min |
| 8 | Measure: count processes before/after | manual | 10min |

**Total Layer 0: ~1.5 hours**

---

## Layer 1: Concept Cannibalization

### 1a. Semantic Tool Filtering

**Problem**: mcpproxy's BM25 (keyword matching) misses semantic relationships.
"記帳" won't match `finance_add_transaction` because there's no keyword overlap.
Our Qwen3-Embedding (1024d) understands Chinese semantic similarity.

**Path**: `core/src/shared/tool_filter.py`

**Architecture**:

```
Startup:
  1. Load all 153 tool definitions (name + description)
  2. Embed each tool description via omlx_bridge.embed_single()
  3. Store as numpy array in memory (~600KB for 153 x 1024d float32)

Query time:
  1. Embed user query via omlx_bridge.embed_single()
  2. Cosine similarity against tool embeddings
  3. Return top-K tools sorted by relevance score

Hybrid (if BM25 available):
  semantic_scores = cosine_similarity(query_emb, tool_embs)
  bm25_scores = mcpproxy_bm25(query)  # via HTTP API
  final = RRF(semantic_scores, bm25_scores)  # Reciprocal Rank Fusion
```

**Key Interfaces**:

```python
# core/src/shared/tool_filter.py

class ToolFilter:
    """Semantic tool filtering using Qwen3-Embedding."""

    def __init__(self, embedding_dim: int = 1024):
        self._tool_embeddings: np.ndarray | None = None  # (N, 1024)
        self._tool_names: list[str] = []
        self._tool_descriptions: list[str] = []

    async def index_tools(self, tools: list[dict]) -> None:
        """Build embedding index from tool definitions.
        tools: [{"name": "...", "description": "..."}, ...]
        Called once at startup or when tool set changes.
        """

    async def query(self, text: str, top_k: int = 10) -> list[dict]:
        """Return top-K tools ranked by semantic similarity.
        Returns: [{"name": "...", "score": 0.87, "description": "..."}, ...]
        """

    async def hybrid_query(
        self, text: str, bm25_results: list[str], top_k: int = 10
    ) -> list[dict]:
        """RRF fusion of semantic + BM25 results."""
```

**Dependencies**: `numpy`, `core/src/shared/omlx_bridge.py` (existing)

**Integration Points**:
- **Standalone utility** (Phase 1): CLI command `workshop tool-filter "記帳"` for debugging
- **mcpproxy enhancement** (Phase 2): mcpproxy supports custom tool filtering via plugins — could write a Go wrapper that calls our Python semantic filter via HTTP
- **Future MCP proxy** (Phase 3): If we self-build, embed directly

**Complexity**: 4 hours (module + tests + CLI)

**Priority**: Medium — mcpproxy BM25 is good enough for English queries; this adds
Chinese semantic understanding which is uniquely valuable for our bilingual environment.

### 1b. Session Profile Manager

**Problem**: Not every session needs all 153 tools. Research sessions don't need
finance tools. Development sessions don't need crawl4ai.

**Path**: `scripts/mcp-profile.sh` (shell script, not Python — fast, no deps)

**Profile Definitions** (stored in `~/.mcpproxy/profiles/`):

```yaml
# ~/.mcpproxy/profiles/full.yaml
name: full
description: All 22 MCP servers (default)
servers: "*"  # all enabled

# ~/.mcpproxy/profiles/dev.yaml
name: dev
description: Core development (8 servers)
servers:
  - sandbox-executor
  - memvault
  - taskflow
  - capture
  - hook-observatory
  - tmux-relay
  - agent-metrics
  - session-intelligence

# ~/.mcpproxy/profiles/research.yaml
name: research
description: Research & intelligence (5 servers)
servers:
  - deepwiki
  - context7
  - crawl4ai
  - intelflow
  - memvault

# ~/.mcpproxy/profiles/finance.yaml
name: finance
description: Finance workflow (5 servers)
servers:
  - finance
  - finance-analytics
  - finance-wallet
  - invest
  - capture

# ~/.mcpproxy/profiles/light.yaml
name: light
description: Minimal (3 servers)
servers:
  - sandbox-executor
  - memvault
  - tmux-relay

# ~/.mcpproxy/profiles/direct.yaml
name: direct
description: Emergency fallback — bypass proxy, direct stdio connections
type: direct  # special: writes individual mcpServers to ~/.claude.json
```

**Mechanism**: mcpproxy supports `upstream enable/disable` commands.
Profile switching = enable matching servers + disable non-matching.

```bash
#!/bin/bash
# scripts/mcp-profile.sh
# Usage: workshop mcp-profile <profile>

PROFILE_DIR="$HOME/.mcpproxy/profiles"
MCPPROXY="$HOME/.local/bin/mcpproxy"

profile="$1"
if [[ "$profile" == "direct" ]]; then
    # Emergency: replace ~/.claude.json with direct connections backup
    cp ~/.claude.json.direct-backup ~/.claude.json
    echo "Switched to direct MCP connections (proxy bypassed)"
    exit 0
fi

profile_file="$PROFILE_DIR/${profile}.yaml"
# Parse YAML, enable/disable servers via mcpproxy upstream enable/disable
# ...
```

**Key Interfaces**:
```bash
workshop mcp-profile full       # Enable all 22 servers
workshop mcp-profile dev        # Enable 8 core dev servers
workshop mcp-profile research   # Enable 5 research servers
workshop mcp-profile light      # Enable 3 minimal servers
workshop mcp-profile direct     # Emergency: bypass proxy
workshop mcp-profile list       # Show available profiles
workshop mcp-profile current    # Show active profile
```

**Dependencies**: `mcpproxy upstream enable/disable` CLI commands, `yq` for YAML parsing

**Integration Points**:
- Shell alias in `~/.zshenv`: `alias mcp-profile='bash ~/workshop/scripts/mcp-profile.sh'`
- Claude Code rule: Can suggest profile switches based on task context
- Hook: `SessionStart` hook could auto-detect task type and suggest appropriate profile

**Complexity**: 2 hours (script + profiles + alias)

**Priority**: High — immediate UX win, reduces tool noise per session.

### 1c. MCP Health Monitor (Sentinel Extension)

**Problem**: mcpproxy manages upstream health internally, but we need visibility
in our existing Sentinel dashboard and alerting pipeline.

**Path**: Extend `stations/sentinel/checker.py`

**Architecture**:

```
Sentinel (existing)
  └── Light Check: mcpproxy HTTP /health  (already in 0e)
  └── NEW: MCP Upstream Health Check
       │
       ├── GET http://127.0.0.1:8808/api/upstreams  (mcpproxy API)
       │   Returns: [{"name": "memvault", "status": "connected", "tools": 8}, ...]
       │
       └── For each upstream with status != "connected":
           → Mark as unhealthy in Sentinel state
           → Trigger remediation (restart upstream via mcpproxy)
```

**Key Interfaces**:

```python
# New LightCheck entries in checker.py:
LightCheck(
    name="mcpproxy",
    group="infra",
    url="http://127.0.0.1:8808/health",
),

# New function in checker.py:
async def check_mcp_upstreams() -> list[CheckResult]:
    """Query mcpproxy API for individual upstream server health.
    Returns one CheckResult per upstream server.
    """
```

**Dashboard Integration**:
- mcpproxy's built-in Web UI at `http://127.0.0.1:8808/ui/` provides real-time monitoring
- Sentinel aggregates mcpproxy health into our unified dashboard
- Bark/ntfy notification on upstream failure (existing alerting pipeline)

**Nginx Reverse Proxy**:
```nginx
# /opt/homebrew/etc/nginx/conf.d/workshop-apps.inc
location /apps/mcpproxy/ {
    proxy_pass http://127.0.0.1:8808/;
    # ... standard proxy headers
}
```

**Dependencies**: mcpproxy REST API (documented), httpx (existing in sentinel)

**Complexity**: 2 hours (checker extension + nginx + testing)

**Priority**: Medium — mcpproxy has its own health monitoring; this adds unified visibility.

---

## Layer 2: Long-term Strategy (Observe Then Decide)

### Decision Matrix

| Condition | Action | Timeline |
|-----------|--------|----------|
| mcpproxy stable 3+ months | Keep as-is, add semantic filter plugin | Month 4+ |
| mcpproxy abandoned / stale | Build Python multiplexer from cannibalized concepts | When needed |
| Claude Code adds native MCP sharing | Deprecate proxy, use native | When available |
| Claude Code adds Streamable HTTP | Simpler proxy config (HTTP mode vs stdio) | When available |

### 2a. If mcpproxy Stays (Most Likely)

**Enhancements**:
1. **Semantic filter sidecar**: HTTP service at port 8809 that mcpproxy queries for tool ranking
2. **Auto-profiling**: Hook that analyzes session context and auto-switches profiles
3. **Tool usage analytics**: Track which tools are actually called per session type → prune unused servers
4. **Quarantine rules**: Auto-disable servers that fail repeatedly (mcpproxy built-in feature)

### 2b. If We Self-Build (Fallback)

**Blueprint for Python multiplexer** (`stations/mcp-proxy/`):

```
stations/mcp-proxy/
├── main.py              # FastAPI app, stdio + HTTP transport
├── upstream.py           # Upstream MCP server manager (spawn + monitor)
├── transport.py          # stdio ↔ JSON-RPC framing
├── filter.py             # Re-use core/src/shared/tool_filter.py
├── health.py             # Upstream health tracking
└── config.py             # Profile + server definitions
```

Key concepts to cannibalize from mcpproxy:
- **Connection pooling**: One set of upstream connections shared across clients
- **Tool filtering**: BM25 + our semantic enhancement
- **Quarantine**: Auto-disable failing upstreams with exponential backoff
- **Web UI**: Real-time status dashboard (can reuse our existing station UI patterns)

**Estimated effort**: 3-5 days (vs mcpproxy which is ready now)

### 2c. If Claude Code Adds Native Sharing

Scenario: Claude Code adds `"shared": true` flag to mcpServers, causing sessions
to reuse a single server process.

**Migration**: Simply add `"shared": true` to each server in `~/.claude.json` and
remove mcpproxy. Keep profiles via direct claude.json manipulation.

---

## Execution Plan

```
Week 1 (Day 1-2): Layer 0 — Immediate Relief
────────────────────────────────────────────────
Day 1 AM  │ [0.1] Add 8 missing servers to mcpproxy config
          │ [0.2] Test mcpproxy serve with 22 upstreams
Day 1 PM  │ [0.3] Replace ~/.claude.json (single proxy entry)
          │ [0.4] Register in workshop_services.py
          │ [0.5] Sentinel check + remediation
Day 2 AM  │ [0.6] Multi-session verification + process count measurement
          │ [0.7] Nginx proxy for mcpproxy Web UI
          │

Week 1 (Day 3-4): Layer 1 — Profiles + Health
────────────────────────────────────────────────
Day 3     │ [1b] Session Profile Manager (script + 5 profiles)  ← HIGH PRIORITY
          │      Can parallelize with:
Day 3     │ [1c] Sentinel MCP upstream health extension
          │
Day 4     │ [1b] Testing + shell integration
          │ [1c] Dashboard integration + alerting
          │

Week 2 (Day 1-2): Layer 1 — Semantic Filter
────────────────────────────────────────────────
Day 5     │ [1a] tool_filter.py implementation
          │ [1a] CLI command for debugging
Day 6     │ [1a] Tests + hybrid RRF scoring
          │ [1a] Integration verification
```

### Parallelization Chart

```
         Day 1      Day 2      Day 3      Day 4      Day 5      Day 6
        ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
Layer 0 │████████████████████ │          │          │          │          │
        │ Config + Test + Deploy        │          │          │          │
        ├──────────┴──────────┼──────────┼──────────┼──────────┼──────────┤
L1b     │                     │██████████████████████│          │          │
Profile │                     │ Script + Profiles + Test       │          │
        ├─────────────────────┼──────────┼──────────┼──────────┼──────────┤
L1c     │                     │████████████████████ │          │          │
Health  │                     │ Sentinel + Nginx    │          │          │
        ├─────────────────────┼──────────┼──────────┼──────────┼──────────┤
L1a     │                     │          │          │████████████████████ │
Semantic│                     │          │          │ Filter + CLI + Test │
        └─────────────────────┴──────────┴──────────┴──────────┴──────────┘
                                L1b ∥ L1c (parallel)
```

---

## Component Summary

| Component | File | Purpose | Deps | Hours | Priority |
|-----------|------|---------|------|-------|----------|
| **L0: Proxy adoption** | `~/.claude.json`, `~/.mcpproxy/mcp_config.json` | Reduce 72+ → ~20 processes | mcpproxy binary | 1.5h | P0 |
| **L0: Service registry** | `scripts/workshop_services.py` | Auto-start/restart proxy | workshop_services | 0.25h | P0 |
| **L0: Health check** | `stations/sentinel/checker.py` | Monitor proxy health | sentinel | 0.25h | P0 |
| **L1b: Profile manager** | `scripts/mcp-profile.sh` | Switch tool sets per context | mcpproxy CLI, yq | 2h | P1 |
| **L1c: Upstream health** | `stations/sentinel/checker.py` | Per-server health in Sentinel | mcpproxy API | 2h | P2 |
| **L1a: Semantic filter** | `core/src/shared/tool_filter.py` | Chinese-aware tool ranking | omlx_bridge, numpy | 4h | P2 |
| **L2: Observe** | (no code) | Decision point at month 3 | runtime data | 0h | P3 |

**Total implementation: ~10 hours across 6 days**

---

## Expected Impact

| Metric | Before | After (L0) | After (L0+L1) |
|--------|--------|-----------|---------------|
| Processes (4 sessions) | 72+ | ~20 | ~20 |
| Processes (1 session) | 18-30 | ~20 (shared) | ~20 (shared) |
| Tools in context per query | ~116 | ~10 (BM25) | ~10 (semantic) |
| Startup time per session | 5-10s (spawn 17 servers) | <1s (connect to proxy) | <1s |
| Memory per session | ~500MB (17 Python processes) | ~20MB (1 stdio pipe) | ~20MB |
| Chinese query accuracy | N/A | Keyword only | Semantic |
| Profile switching | Manual edit | `mcp-profile dev` | `mcp-profile dev` |

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| mcpproxy crashes | workshop_services.py auto-restart (60s cycle) |
| mcpproxy version breaking change | Pin version, test before upgrade |
| BM25 misses critical tool | `top_k: 10` covers ~65% of total; raise to 15 if needed |
| Upstream server hangs | mcpproxy built-in timeout + quarantine |
| Claude Code changes MCP protocol | mcpproxy community will likely adapt; fallback to direct |
| `~/.claude.json` backup lost | Git-tracked in dotfiles repo |

---

## Notes

- mcpproxy v0.20.2 at `~/.local/bin/mcpproxy`, config at `~/.mcpproxy/mcp_config.json`
- The proxy's Web UI at `http://127.0.0.1:8808/ui/` provides excellent real-time monitoring
- mcpproxy supports both stdio (for Claude Code) and HTTP (for Web UI / API) simultaneously
- Our 22 MCP servers expose 153 tools total; Claude Code currently loads 17 servers (~116 tools)
- The BM25 `top_k: 10` filter is the single biggest context token saver
