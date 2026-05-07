# Audit Steps 5-8 — Status Report (issue #31)

Verified 2026-05-07. Branch `fix/audit-systemic-step5to8`, 6 commits.

## Done in this PR

| # | Finding | Commit |
|---|---------|--------|
| Step 8 | invest position IDOR — propagate space_id | `94dbc716` |
| Step 8 | taskflow task IDOR — transition + updates endpoints | `90793c1d` |
| Step 8 | nodeflow flow IDOR — propagate space_id through lifecycle + edges | `cb56666a` |
| Step 5 | memvault block IDOR — propagate space_id to update/delete/invalidate/restore | `56f6cd52` |
| Step 6 | dailyos timezone — TimezoneResolver + Clock service replaces date.today() | `516b61ce` |
| Step 6 | dailyos ritual write side — complete_morning_ritual/complete_evening_ritual | (this commit) |

## Not done — follow-up issue recommended

### High severity (do next)
- [ ] **shared/services.py** — verify whether BaseCRUDService already has
  `get_in_space()/update_in_space()/delete_in_space()` helpers. The five IDOR
  fixes above were done at the per-service level; consolidating into a
  base helper would prevent regression in future services.
- [ ] **dailyos WorkflowService.activate()** — currently a no-op; needs to
  flip `active=True` and emit `dailyos.workflow.activated` event.
- [ ] **dailyos ritual routes.py wire** — service methods exist but no HTTP
  endpoint. Add `POST /api/dailyos/ritual/morning/complete` and
  `/evening/complete` plumbed to the new service methods.
- [ ] **notification redis_listener** — no exponential-backoff reconnect on
  Redis disconnect; one disconnect kills the listener until process restart.
- [ ] **paper digest_generator** — prompt injection guardrail for
  user-controlled paper titles entering the digest LLM prompt (escape
  `[INST]` / `</s>` / role-marker patterns).
- [ ] **nodeflow** — three Step 8 highs: action executor `TypeError` on raw
  service method invocation, wildcard event handler self-trigger storm,
  DAG cycle silently marked completed.

### Medium severity (P2)
- [ ] memvault attitude `ALWAYS_MERGE` arbitration
- [ ] memvault `source_session` server-only enforcement (anti-spoofing)
- [ ] dailyos `effective_config` persistence on DailyPlan
- [ ] memvault Qdrant MMR/semantic_boost re-enable (embeddings missing in returns)
- [ ] notification push payload schema validation
- [ ] briefing SSE replay/resume
- [ ] notification bounded queue + backpressure
- [ ] arxiv_fetcher unbounded response read
- [ ] intelflow LIKE wildcard injection
- [ ] invest refresh_quotes staleness gate
- [ ] invest fee/tax in calculations + Decimal preservation

## Why this PR stopped here

Background `general-purpose` agent stalled on the design choice for ritual
write semantics (read-as-completion vs explicit `complete()` endpoint).
Stream watchdog killed it after 600s of no progress. The 5 IDOR commits
plus the ritual-write service methods were already on disk and have been
preserved here. Recommend reopening this issue (or splitting into
per-module follow-ups) for the items above.

## Out of scope

- finance IDOR / FOR UPDATE / outbox — covered by sibling PR for issue #30
  (branch `fix/audit-finance-step4`).
