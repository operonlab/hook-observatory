---
source_hash: 5e8f6263
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# LLM Usage Workstation

> Unified LLM usage tracking — subscription-based CLI tool usage + LiteLLM API costs.

## Positioning

An independent workstation under Workshop `stations/`, providing unified usage and cost tracking across LLM services.

## V1 Assets

| Component | Location | Status |
|------|------|------|
| `model-policy.py` | `~/.claude/scripts/model-policy.py` | Operational, tracking Claude Code 5h/7d usage |
| `state.json` | `~/.claude/data/model-policy/state.json` | boost/normal mode switching |
| LiteLLM Proxy | `~/.config/litellm/` | Operational, unified LLM API routing |
| LiteLLM DB | LiteLLM internal SQLite | Has token/cost records but they are not utilized |

## Problem Analysis

Currently, LLM usage is scattered across two different worlds, making it impossible to answer "How much was used this month? How much did it cost?" in a unified way:

```
── Subscription-based CLI Tools (Subscription) ──────────────
Claude Code → Anthropic Max Plan → Usage ratio (5h/7d window)
Codex CLI   → OpenAI (ChatGPT)   → Usage not transparent
Gemini CLI  → Google (Gemini)    → Usage not transparent
model-policy → Only looks at CC ratio → Used for boost/normal switching

── API Services (Pay-per-use) ─────────────────────
LiteLLM     → Multiple Provider APIs → SQLite (Has data but no UI)
(Used for self-built Agent scenarios like Anthropic Agent SDK)
```

## V2 Goals

### 1. Dual-track Data Collection

```
┌── Subscription-based CLI Tools (Subscription)─────────────────────┐
│                                                       │
│  Claude Code → session hooks → usage ratio + session stats │
│  Codex CLI   → session logs  → call count + estimation        │
│  Gemini CLI  → session logs  → call count + estimation        │
│                                                       │
│  Characteristic: Fixed monthly fee, tracks "usage quota" not "actual cost"       │
│  Data Sources: hooks, CLI logs, provider dashboard scrape  │
└───────────────────────────────────────────────────────┘

┌── API Services (Pay-per-use via LiteLLM)────────────────┐
│                                                       │
│  Agent SDK ─┐                                         │
│  Self-built services  ─┼─► LiteLLM Proxy ─► DB (token + cost)   │
│  Experimental scripts ─┘     (Unified routing)                           │
│                                                       │
│  Characteristic: Pay-per-use, tracks "actual token count + cost"          │
│  Data Sources: LiteLLM SQLite (real-time) + Provider API (reconciliation)│
└───────────────────────────────────────────────────────┘
```

**The two data streams are fundamentally different**:
- **Subscription-based**: Tracks consumption ratio of usage quota (e.g., 30% of CC 5h window used), fixed monthly fee
- **API Services**: Tracks actual token consumption + cost (LiteLLM Proxy records every call), pay-per-use

### 2. Data Model

**Subscription Usage Record**:
```json
{
  "subscription_usage": {
    "id": "uuid",
    "timestamp": "2026-02-24T10:30:00Z",
    "provider": "anthropic",        // anthropic / openai / google
    "cli": "claude-code",           // claude-code / codex-cli / gemini-cli
    "plan": "max_5",                // max_5 / max_20 / pro / advanced
    "monthly_cost_usd": 100.00,    // Fixed monthly cost
    "quota_used_pct": 30.0,        // Quota consumption ratio (e.g., CC 5h window)
    "session_count": 15,           // Session count for the day
    "session_id": "optional",
    "task_type": "coding"           // coding / research / chat / briefing
  }
}
```

**API Usage Record**:
```json
{
  "api_usage": {
    "id": "uuid",
    "timestamp": "2026-02-24T10:30:00Z",
    "provider": "anthropic",        // anthropic / openai / google / ollama
    "model": "claude-sonnet-4-6",
    "caller": "agent-sdk",          // agent-sdk / script / service
    "input_tokens": 15000,
    "output_tokens": 3200,
    "cache_read_tokens": 8000,
    "cache_write_tokens": 2000,
    "cost_usd": 0.042,
    "task_id": "optional",
    "litellm_call_id": "optional"
  }
}
```

### 3. Analysis Dimensions

| Dimension | Subscription | API Service |
|------|--------|----------|
| **By Provider** | Total monthly fee for each platform | Actual cost for each Provider |
| **By Model** | — | Cost breakdown of Opus vs Sonnet vs Haiku |
| **By CLI/Caller** | Usage ratio of CC vs Codex vs Gemini | Agent SDK vs scripts |
| **By Time** | Daily session count + quota trend | Daily/weekly/monthly tokens + cost |
| **By Purpose** | coding / research / briefing | Categorized by task |
| **Cache Efficiency** | — | cache hit rate, how much money was saved |
| **Total Cost** | Σ Monthly fees (fixed) | Σ API costs (variable) |

### 4. Model Policy Integration

The existing model-policy boost/normal switching logic will continue to operate, with the data source changed to the unified DB:

```
V1: model-policy calculates the CC 5h/7d usage ratio itself
  ↓
V2: model-policy reads subscription usage from the LLM Usage DB → more accurate switching decisions
    (And can also reference API costs to decide whether to switch back to subscription tools to save costs)
```

## API Endpoints (`/api/stations/llm-usage/`)

| Method | Path | Description |
|------|------|------|
| GET | `/summary` | Overview (today/this week/this month's token count + cost) |
| GET | `/records` | List of usage records (filter by provider/model/caller, pagination) |
| GET | `/breakdown` | Multi-dimensional breakdown (by provider/model/caller/time) |
| GET | `/trends` | Trend data (for time-series charts) |
| GET | `/budget` | Budget tracking (set monthly limit vs actual spending) |
| POST | `/budget` | Set budget limit |
| POST | `/sync` | Manually trigger LiteLLM DB sync |
| GET | `/cache-stats` | Cache efficiency statistics |

## Workbench Widget

Dashboard home page card:

```
┌─── LLM Usage ─── February 2026 ────────┐
│                                         │
│  ── Subscription (Fixed Monthly Cost) ──                │
│  Anthropic Max:  $100/mo  CC 5h: 30%   │
│  OpenAI Pro:      $20/mo               │
│  Gemini Advanced: $20/mo               │
│  Subtotal: $140/mo                          │
│                                         │
│  ── API Services (Pay-per-use) ──              │
│  LiteLLM: $12.30 / $50 budget  🟢     │
│  ████████░░░░░░░░░░░░░  25%            │
│  Today: 45K tokens ($1.20)              │
│  Cache savings: $3.80 this month        │
│                                         │
│  ── Total ──                             │
│  This month: $152.30 (Fixed $140 + API $12.30) │
│  [View Details →]                       │
└─────────────────────────────────────────┘
```

## Directory Structure

```
stations/llm-usage/
├── README.md             ← This document
├── subscription.py       ← Subscription usage collection (CC hooks, CLI logs)
├── api_collector.py      ← LiteLLM DB sync + Provider API reconciliation
├── analyzer.py           ← Dual-track analysis engine
├── config.json           ← Subscription plan settings, API budget, sync frequency
└── policy_adapter.py     ← model-policy integration (reads from unified DB)
```

## Migration Plan

1. Organize subscription plan information (plan + monthly cost + quota calculation method for each CLI)
2. Parse the LiteLLM SQLite DB structure and create an API usage sync script
3. Create the dual-track data model (subscription_usage + api_usage)
4. Implement the subscription collector (CC hooks → session stats + quota ratio)
5. Implement the api_collector (sync LiteLLM to unified DB hourly)
6. Create Core API endpoints
7. Rewrite model-policy to read from the unified DB
8. Create Workbench Widget (dual-track cost dashboard)
9. (Optional) Integrate with Provider billing APIs for API service reconciliation

## Dependencies

- **station-sdk** (`libs/python/station-sdk/`) — Core API push, Widget data format, notification integration (see [AD-8](../../docs/architecture/architecture-decisions.md#ad-8-station-sdk--工作站共享層))
- **LiteLLM Proxy** — Main data source
- **model-policy** — Existing boost/normal switching logic
- **Core API** (Optional) — Persist to PostgreSQL
- **notification bridge** (Optional) — Budget overrun alerts

## References

- Model Policy: `~/.claude/scripts/model-policy.py`
- Model Policy State: `~/.claude/data/model-policy/state.json`
- LiteLLM Config: `~/.config/litellm/`
- LiteLLM Docs: https://docs.litellm.ai/
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3432ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3078ms
