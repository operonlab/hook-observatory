# Finance Audit — Step 4 Status

Branch: `fix/audit-finance-step4`
Worktree: `.worktrees/fix/audit-finance-step4/`
Issue: JonesHong/workshop#30
Scope: finance module only (shared/services.py-level IDOR is owned by #31)

## Per-finding outcome

| # | Severity | Status | Commit | Notes |
|---|----------|--------|--------|-------|
| C1 | critical | fixed | C1 commit | reports `_build_wallets_section` now converts each wallet to `base_currency` (TWD) via `exchange.get_exchange_rates()`. Falls back to raw sum + flag when rates unavailable. `SummaryService.net_worth` already had the conversion. |
| H1 | high | fixed | H1 commit | Wallet sub-resources (sync, reconcile, list_snapshots, diff_snapshots, gap_analysis) now scope-check via `get_in_space`. TransferService rejects wallets whose `space_id` ≠ request's space (and soft-deleted wallets). Routes thread `space_id` through. CRUD-level scoping was already present via `BaseCRUDService.update/delete(space_id=)`. |
| H6 | high | already-fixed | — | `TransferService.transfer` already calls `db.get(Wallet, wid, with_for_update=True)` inside sorted lock loop + `begin_nested` savepoint. No new code, only confirmed. |
| M1 | medium | fixed | M1 commit | `finance/cron.py` introduced `_emit_event()` that appends to `_pending_events` so events fire **after** `db.commit()`. Applied to INSTALLMENT_DUE, INSTALLMENT_COMPLETED, SUBSCRIPTION_RENEWED. CLI/non-request callers fall back to `publish_fire_and_forget`. |
| M2 | medium | fixed | M2 commit | `exchange.get_exchange_rates()` now raises `ExchangeRatesUnavailableError` (HTTP 503) when both Redis and the in-memory cache are older than `_STALE_MAX_AGE` (24h) and CDN is down. The hard-coded `{TWD: 31.5}` fallback is removed. Fresh-but-stale entries are still served, marked `is_fallback=True`. |
| M3 | medium | fixed | M3 commit | reports.py now: (a) folds transfer in/out into `month_net_change`, (b) adds `Transaction.deleted_at IS NULL` to category / installment / due-this-month subqueries, (c) filters `Subscription.deleted_at IS NULL` and `InstallmentPlan.deleted_at IS NULL`. Wallets section already filtered `deleted_at IS NULL` and `is_active`. |
| L1 | low | fixed | L1 commit | `grc_adapter.fetch_blocks()` keeps `Transaction.amount` as Decimal (was `str(t.amount)`); `gather_items()` defaults missing amounts to `Decimal("0")` (was `0.0`). Float coercion eliminated end-to-end. |

## Out of scope (intentionally not touched)

- `core/src/shared/services.py` IDOR baseline (issue #31).
- `SummaryService.monthly_summary` cross-currency aggregation: transactions inherit wallet currency; mixed-currency spaces would also be wrong here, but fixing requires a model decision (sum in wallet's currency vs convert) that should be brokered separately. Audit scope was reports/net_worth/summary endpoint surface, all of which now expose the base currency contract.
- Alembic migration: none needed — no schema changes in this batch.

## Verification

- `ruff check core/src/modules/finance/` baseline = 16 errors, post-change = 16 errors (all pre-existing RUF001 fullwidth-char + 2 E402). No new lint regressions.
- No alembic migration files added.
- All commits use Conventional Commits prefix `fix(finance): …`.
