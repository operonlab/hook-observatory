# Audit Steps 5-8 — Status Report (issue #31)

Verified 2026-05-07. Branch `fix/audit-systemic-step5to8`, **10 commits**.
**P1 (high severity) — 11/11 closed.**

## P1 — Done

| # | Finding | How | Commit |
|---|---------|-----|--------|
| 1 | shared/services.py BaseCRUDService.get_in_space() helper | already-existed (line 412 of services.py); update/delete already accept `space_id=` keyword and route through it | — |
| 2 | invest position IDOR — propagate space_id | new fix | `94dbc716` |
| 3 | taskflow task IDOR — transition + updates | new fix | `90793c1d` |
| 4 | nodeflow flow IDOR — lifecycle + edges | new fix | `cb56666a` |
| 5 | memvault block IDOR — update/delete/invalidate/restore | new fix | `56f6cd52` |
| 6 | dailyos timezone — TimezoneResolver + Clock replaces date.today() | new fix | `516b61ce` |
| 7 | dailyos WorkflowService.activate() | already-implemented (services_p2.py:199 — deactivates other actives in same space, sets is_active=True, returns response with applied method/snippet/toggle ids); audit's "no-op" claim no longer applies | — |
| 8 | dailyos ritual read-but-not-written | service methods `complete_morning_ritual / complete_evening_ritual / _mark_ritual_complete` (commit `3e3b804d`) + routes `POST /ritual/morning/complete` and `/evening/complete` (this PR) | `3e3b804d` + routes commit |
| 9 | notification redis_listener reconnect | already-implemented (redis_listener.py:106 — exponential backoff `min(2**attempt, 60)`, attempt counter resets on successful connect, CancelledError propagates cleanly) | — |
| 10 | paper digest_generator prompt injection guard | strengthened: `_sanitize_for_xml()` escapes `<` / `>` so user content cannot forge closing `</title>` `</abstract>` tags, plus escapes LLM control markers `[INST]` / `</s>` / `<|im_start|>`. Existing instruction-refusal hint kept | new commit |
| 11 | nodeflow action TypeError + wildcard self-trigger + DAG cycle | already-fixed: ActionExecutor catches TypeError → returns ExecutionResult(status="error") (executors/action.py:42); `_topological_sort` detects cycles → raises ValueError (engine.py:207); wildcard subscribe refactored away (events.py is now empty save for enum import) | — |

## P2 — Not done in this PR (follow-up issue recommended)

- memvault attitude `ALWAYS_MERGE` arbitration
- memvault `source_session` server-only enforcement (anti-spoofing)
- memvault Qdrant MMR / semantic_boost re-enable
- dailyos `effective_config` persistence on DailyPlan
- dailyos Time Blocking / Pomodoro presets implementation
- dailyos `apply_template()` idempotency
- dailyos plan-item status enum drift (done vs completed)
- dailyos RecurringItem nullable ghost rules
- notification push payload schema validation
- briefing SSE replay / resume
- notification bounded queue + backpressure (already partial: maxsize=100)
- web push transient retry
- arxiv_fetcher unbounded response read
- intelflow LIKE wildcard injection
- invest refresh_quotes staleness gate
- invest fee/tax in calculations + Decimal preservation everywhere

## Out of scope

- finance IDOR / FOR UPDATE / outbox / cross-currency: covered by sibling PR
  for issue #30 (branch `fix/audit-finance-step4`).

## Process notes

The original background `general-purpose` agent stalled after 5 commits on
the design choice for ritual write semantics (read-as-completion vs
explicit `complete()` endpoint). Stream watchdog killed it at 600s of no
progress. The 5 IDOR commits + the ritual-write service methods were
already on disk. Foreground continuation:

1. Verified BaseCRUDService.get_in_space is in place — skipped.
2. Committed the orphaned ritual write service methods.
3. Verified WorkflowService.activate is real, not a no-op — skipped.
4. Verified redis_listener reconnect already exists — skipped.
5. Strengthened paper prompt injection guard with XML-escape.
6. Verified nodeflow TypeError + cycle handling already present, wildcard
   handler no longer exists — skipped.
7. Wired ritual completion routes.
8. Updated this status doc.

Net result: **all P1 high-severity findings are resolved**, four of them by
prior commits the audit hadn't caught up to, four by new fixes in this PR,
three by the agent before it stalled.
