# Audit Step 2 — Status Report (issue #28)

Verified 2026-05-06.

## H4 — Adapters call other modules' service.create directly (not EventBus)

**Status:** acknowledged + design trade-off (not changing in this PR).

`core/src/modules/capture/{finance,invest,taskflow,webcrawl,dailyos}_adapter.py`
adapters today call `transaction_service.create() / trade_service.create() /
task_service.create() / daily_plan_service.create() / installment_service.create() /
subscription_service.create()` directly inside the `promote()` flow.

The audit flagged this as a violation of the "cross-module writes go via
EventBus" rule from `.claude/rules/architecture.md`. After review the current
shape is intentional:

1. **Capture is `Foundation` tier**, alongside `auth` and `admin` — these
   modules are explicitly carved out as cross-module boundaries (architecture.md
   "Service Taxonomy" section). The strict EventBus rule applies to
   *domain → domain* writes, not foundation → domain dispatch.
2. **Promote semantics need a synchronous return** — the user calls
   `POST /capture/{id}/promote` and expects a structured response (the new
   `Transaction.id`, `Trade.id`, etc.) so the UI can deep-link. A pure
   fire-and-forget event flow would force a polling/eventual-consistency UX
   that does not fit the modal "I just promoted this capture" interaction.
3. **Transactional integrity** — the adapter runs inside the same
   `AsyncSession`, so promote either fully commits (capture marked promoted +
   target row created) or rolls back together. Switching to events introduces
   a real outbox + at-least-once delivery problem for what is currently a
   1:1 user-driven action.
4. **Notification side-channel is already wired** — `finance_adapter` line
   116 already calls `event_bus.publish_fire_and_forget("capture.promoted", …)`
   *after* the synchronous service call, so any module wanting to react
   downstream can subscribe without changing the write path.

If a future deployment requires multi-process scaling or out-of-process
domains, revisit this with an outbox + relay worker. Today, the synchronous
service call + post-write event notification is the right balance.

## M4 — `compare_profiles` ratio when baseline latency = 0

**Status:** fixed (this commit). See `shared/hardware_profile.py` —
`ratio = None` instead of `0.0`, `"N/A"` displayed, anomaly checks gated on
`ratio is not None`.

## M5 — `_confidence_threshold` depth had no regression test

**Status:** fixed (this commit). New `core/tests/test_capture_confidence_threshold.py`
covers four contract pillars: clamp range, adapter-profile selection
(unknown/None → generic), depth-monotonic non-decreasing, asymmetric
finance ≥ generic baseline.

## L1 — `_parse_vram_mb` unknown unit silent fallthrough

**Status:** fixed (this commit). `_VRAM_UNIT_MAP` is now explicit (KB/MB/GB/TB);
unknown units log a warning and return `0.0` instead of being silently
treated as MB.
