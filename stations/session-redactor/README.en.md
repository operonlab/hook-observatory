---
source_hash: 32330c8d
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Session Redactor Workstation

> Redacting sensitive data from transcripts — triggered by the SessionEnd hook to scan .jsonl files and remove secrets like API keys, passwords, and tokens.

## Positioning

An independent workstation under `Workshop stations/`. It automatically scans transcripts at the end of a Claude Code session to redact sensitive data, ensuring that the subsequent `lore` memory extraction process does not come into contact with the original secrets.

## Position in the SessionEnd Pipeline

```
SessionEnd Hook Triggered
  │
  ├── 1️⃣  session-redactor    ← First, redact sensitive data (this tool)
  │       Scans .jsonl → Removes API keys / passwords / tokens
  │       ↓ Cleaned transcript
  ├── 2️⃣  lore extract        ← Extract memories from the clean transcript
  │       Extracts memories → Creates Galaxy
  │
  └── 3️⃣  observability       ← Log event
```

**Why not merge it into lore**:
- Single Responsibility: Secure redaction ≠ knowledge management
- Fault Isolation: If redactor fails → lore still runs (it's better to not redact than to block memory extraction)
- Different Update Cadences: The frequency of updating sensitivity patterns ≠ the frequency of updating memory extraction logic
- Reusability: redactor also cleans transcripts from other tools like `recall` (zippoxer)

## V1 Assets

| Component | Location | Description |
|------|------|------|
| `redact-session.sh` | V1: `~/Claude/projects/session-redactor/scripts/` | SessionEnd hook entry point (non-blocking) |
| `redactor.py` | `src/session_redactor/` | Core redaction logic (JSON parse + regex + atomic write) |
| `patterns.py` | `src/session_redactor/` | Definitions for 16 types of sensitive patterns |
| `scanner.py` | `src/session_redactor/` | Daily full scan at 4 AM |
| `db.py` | `src/session_redactor/` | SQLite for tracking history |
| SQLite DB | `~/.local/share/workshop/session_redactor.sqlite` | Redaction logs |

## Detected Sensitive Patterns (16 Types)

| Category | Pattern |
|------|------|
| **Passwords** | `echo "xxx" \| sudo -S`, Chinese "密碼是：xxx" (password is: xxx), `password = "xxx"`, and variants with different quotes/parentheses |
| **API Keys** | Anthropic `sk-ant-*`, OpenAI `sk-*`, GitHub `ghp_*/ghs_*` |
| **Tokens** | Bearer tokens (20+ characters) |
| **AWS** | Access keys starting with `AKIA`, `AWS_SECRET` environment variables |
| **SSH** | `-----BEGIN ... PRIVATE KEY-----` |
| **DB Connections** | `://user:password@host` format |
| **Generic** | `password/secret/token/api_key = [value]` regular expressions |

## Trigger Mechanisms

| Trigger Method | When | Description |
|---------|------|------|
| **SessionEnd Hook** | At the end of every Claude Code session | Non-blocking: spawns a background process + disown, immediately returns exit 0 |
| **Daily Sweep** | Daily at 4 AM | `scanner.py` performs a full scan of all .jsonl files |
| **Manual** | Anytime | By directly calling the Python module |

## Workflow

```
SessionEnd event (stdin JSON)
    ↓
redact-session.sh (background subprocess)
    ↓
Python redactor.redact_file()
    ├── Read .jsonl (session transcript)
    ├── Parse JSON line by line
    ├── Recursively traverse all string values and apply the 16 PATTERNS
    ├── If modified: atomic write (.tmp → rename)
    └── Log to SQLite (track redaction history)
```

## Directory Structure (Planned)

```
stations/session-redactor/
├── README.md                  ← This document
├── scripts/
│   └── redact-session.sh      ← SessionEnd hook entry point
├── src/session_redactor/
│   ├── __init__.py
│   ├── redactor.py            ← Core redaction logic
│   ├── patterns.py            ← 16 sensitive patterns
│   ├── scanner.py             ← Daily sweep
│   ├── db.py                  ← SQLite CRUD
│   └── config.py              ← Configuration (scan time, DB path, etc.)
└── pyproject.toml
```

## Migration Plan

1. Copy V1 `~/Claude/projects/session-redactor/` to `stations/session-redactor/`
2. Update the hook path in `~/.claude/settings.json` to point to the new location
3. Confirm the SessionEnd pipeline order: redactor → lore extract → observability
4. (Optional) Migrate SQLite → PostgreSQL and integrate redaction statistics with the Core API

## Dependencies

- **Claude Code hooks** — For SessionEnd triggers
- **lore pipeline** (indirect) — redactor must run before lore extract
- **SQLite** — For tracking redaction logs

## References

- V1 Location (migrated): `~/Claude/projects/session-redactor/`
- Hook Configuration: `~/.claude/settings.json` (SessionEnd entries)
- SQLite DB: `~/.local/share/workshop/session_redactor.sqlite`
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3252ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2529ms
