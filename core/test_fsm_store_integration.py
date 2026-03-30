#!/usr/bin/env python3
"""Independent FSM→Store integration test — Six Iron Rules.

Independent tester: NOT the writer. Mission: FIND BUGS, not confirm correctness.
"""

import asyncio
import sys
import traceback

sys.path.insert(0, "/Users/joneshong/workshop/core")

PASS = "PASS"
FAIL = "FAIL"

results = []


def report(status, name, desc, expected=None, actual=None, extra=None):
    results.append((status, name, desc, expected, actual, extra))
    marker = "✅" if status == PASS else "❌"
    print(f"[{status}] {name} — {desc}")
    if status == FAIL:
        if expected is not None:
            print(f"  Expected: {expected}")
        if actual is not None:
            print(f"  Actual:   {actual}")
        if extra:
            print(f"  Detail:   {extra}")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def make_fresh_store(module_name: str):
    """Import + return a *fresh* FeatureStore for a module (no shared state)."""
    # Force re-import to get clean store instances
    # We patch the event_bus so no real Redis needed
    if module_name == "auth":
        from src.modules.auth.store import StateTransitioned, auth_store

        return auth_store, StateTransitioned
    elif module_name == "briefing":
        from src.modules.briefing.store import StateTransitioned, briefing_store

        return briefing_store, StateTransitioned
    elif module_name == "finance":
        from src.modules.finance.store import StateTransitioned, finance_store

        return finance_store, StateTransitioned
    elif module_name == "taskflow":
        from src.modules.taskflow.store import StateTransitioned, taskflow_store

        return taskflow_store, StateTransitioned
    elif module_name == "nodeflow":
        from src.modules.nodeflow.store import StateTransitioned, nodeflow_store

        return nodeflow_store, StateTransitioned
    else:
        raise ValueError(f"Unknown module: {module_name}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Cross-module — StateTransitioned exists in all 5 stores
# ─────────────────────────────────────────────────────────────────────────────


async def test_state_transitioned_exists_in_all_modules():
    """Verify StateTransitioned action creator exists in all 5 modules."""
    modules = ["auth", "briefing", "finance", "taskflow", "nodeflow"]
    for mod in modules:
        try:
            store, ST = make_fresh_store(mod)
            assert ST is not None, f"StateTransitioned is None in {mod}"
            assert hasattr(ST, "type"), f"StateTransitioned.type missing in {mod}"
            report(
                PASS,
                f"test_state_transitioned_exists[{mod}]",
                f"StateTransitioned defined in {mod}.store, type={ST.type!r}",
            )
        except Exception as e:
            report(
                FAIL,
                f"test_state_transitioned_exists[{mod}]",
                f"StateTransitioned missing or import error in {mod}",
                expected="ActionCreator with .type",
                actual=str(e),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Schema invariant — event format MUST match old emit_state_changed
# ─────────────────────────────────────────────────────────────────────────────


async def test_schema_invariant_vs_emit_state_changed():
    """
    Old emit_state_changed produced:
      type  = f"{module}.{entity_type}.state_changed"
      data  = {"entity_id": ..., "old_state": ..., "new_state": ..., **extra}
      source = f"{module}.fsm"       <-- NOTE: .fsm not .store
      user_id = user_id

    New publish_state_changed effect must produce the same format EXCEPT
    source is now f"{module}.store".

    Test also checks: event data keys, event type format.
    """
    modules = ["auth", "briefing", "finance", "taskflow", "nodeflow"]

    for mod in modules:
        captured_events = []

        async def fake_publish(event, _captured=captured_events):
            _captured.append(event)

        try:
            store, ST = make_fresh_store(mod)
            # Patch event_bus.publish on the store's lazily resolved bus
            from src.events.bus import event_bus

            original_publish = event_bus.publish
            event_bus.publish = fake_publish

            try:
                action = ST(
                    module=mod,
                    entity_type="user",
                    entity_id="eid-001",
                    old_state="pending",
                    new_state="active",
                    user_id="uid-999",
                )
                await store.dispatch(action)
                # Give fire-and-forget time to complete
                await asyncio.sleep(0.05)
            finally:
                event_bus.publish = original_publish

            # Filter for state_changed events (ignore other effects)
            sc_events = [e for e in captured_events if e.type.endswith(".state_changed")]

            if not sc_events:
                report(
                    FAIL,
                    f"test_schema_invariant[{mod}]",
                    "No state_changed event emitted",
                    expected=f"{mod}.user.state_changed",
                    actual="(no events captured)",
                )
                continue

            evt = sc_events[0]
            errors = []

            # Check event type
            expected_type = f"{mod}.user.state_changed"
            if evt.type != expected_type:
                errors.append(f"type: expected={expected_type!r}, actual={evt.type!r}")

            # Check data keys
            for key in ("entity_id", "old_state", "new_state"):
                if key not in evt.data:
                    errors.append(f"data missing key: {key!r}")

            # Check data values
            if evt.data.get("entity_id") != "eid-001":
                errors.append(
                    f"entity_id: expected='eid-001', actual={evt.data.get('entity_id')!r}"
                )
            if evt.data.get("old_state") != "pending":
                errors.append(
                    f"old_state: expected='pending', actual={evt.data.get('old_state')!r}"
                )
            if evt.data.get("new_state") != "active":
                errors.append(f"new_state: expected='active', actual={evt.data.get('new_state')!r}")

            # Check source — must be {module}.store (NOT {module}.fsm)
            expected_source = f"{mod}.store"
            if evt.source != expected_source:
                errors.append(f"source: expected={expected_source!r}, actual={evt.source!r}")

            if errors:
                report(
                    FAIL,
                    f"test_schema_invariant[{mod}]",
                    "Event format mismatch",
                    expected="Correct type/data/source",
                    actual="; ".join(errors),
                )
            else:
                report(
                    PASS,
                    f"test_schema_invariant[{mod}]",
                    f"Event format correct: type={evt.type!r}, source={evt.source!r}",
                )

        except Exception:
            report(
                FAIL,
                f"test_schema_invariant[{mod}]",
                "Exception during dispatch",
                actual=traceback.format_exc(),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: user_id passthrough
# ─────────────────────────────────────────────────────────────────────────────


async def test_user_id_passthrough():
    """user_id MUST appear in the published EventBus event."""
    modules = ["auth", "briefing", "finance", "taskflow", "nodeflow"]

    for mod in modules:
        captured_events = []

        async def fake_publish(event, _captured=captured_events):
            _captured.append(event)

        try:
            store, ST = make_fresh_store(mod)
            from src.events.bus import event_bus

            original_publish = event_bus.publish
            event_bus.publish = fake_publish

            try:
                action = ST(
                    module=mod,
                    entity_type="document",
                    entity_id="doc-42",
                    old_state="draft",
                    new_state="published",
                    user_id="user-XYZ",
                )
                await store.dispatch(action)
                await asyncio.sleep(0.05)
            finally:
                event_bus.publish = original_publish

            sc_events = [e for e in captured_events if e.type.endswith(".state_changed")]

            if not sc_events:
                report(
                    FAIL,
                    f"test_user_id_passthrough[{mod}]",
                    "No state_changed event emitted",
                    expected="event with user_id='user-XYZ'",
                    actual="(no events)",
                )
                continue

            evt = sc_events[0]
            if evt.user_id == "user-XYZ":
                report(
                    PASS,
                    f"test_user_id_passthrough[{mod}]",
                    "user_id correctly passed to EventBus event",
                )
            else:
                report(
                    FAIL,
                    f"test_user_id_passthrough[{mod}]",
                    "user_id NOT passed to EventBus event",
                    expected="user_id='user-XYZ'",
                    actual=f"user_id={evt.user_id!r}",
                )

        except Exception:
            report(
                FAIL,
                f"test_user_id_passthrough[{mod}]",
                "Exception during dispatch",
                actual=traceback.format_exc(),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: No-op reducer — store state MUST NOT change after StateTransitioned
# ─────────────────────────────────────────────────────────────────────────────


async def test_noop_reducer():
    """Store state must remain identical after StateTransitioned dispatch."""
    modules = ["auth", "briefing", "finance", "taskflow", "nodeflow"]

    for mod in modules:
        captured_events = []

        async def fake_publish(event, _captured=captured_events):
            _captured.append(event)

        try:
            store, ST = make_fresh_store(mod)
            from src.events.bus import event_bus

            original_publish = event_bus.publish
            event_bus.publish = fake_publish

            state_before = store.get_state()

            try:
                action = ST(
                    module=mod,
                    entity_type="item",
                    entity_id="item-1",
                    old_state="inactive",
                    new_state="active",
                )
                await store.dispatch(action)
                await asyncio.sleep(0.05)
            finally:
                event_bus.publish = original_publish

            state_after = store.get_state()

            if state_before == state_after:
                report(
                    PASS,
                    f"test_noop_reducer[{mod}]",
                    "Store state unchanged after StateTransitioned",
                )
            else:
                # Find what changed
                changed_keys = [
                    k
                    for k in set(list(state_before.keys()) + list(state_after.keys()))
                    if state_before.get(k) != state_after.get(k)
                ]
                report(
                    FAIL,
                    f"test_noop_reducer[{mod}]",
                    "Store state changed after StateTransitioned (should be no-op)",
                    expected="state unchanged",
                    actual=f"changed keys: {changed_keys}",
                )

        except Exception:
            report(
                FAIL,
                f"test_noop_reducer[{mod}]",
                "Exception during test",
                actual=traceback.format_exc(),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Mutation — empty/None fields (robustness)
# ─────────────────────────────────────────────────────────────────────────────


async def test_mutation_empty_fields():
    """Dispatch StateTransitioned with missing/None fields — must NOT crash."""
    modules = ["auth", "briefing", "finance", "taskflow", "nodeflow"]

    cases = [
        ("no_payload", None),
        ("empty_dict", {}),
        (
            "missing_entity_id",
            {
                "module": "auth",
                "entity_type": "user",
                "old_state": "pending",
                "new_state": "active",
            },
        ),
        (
            "missing_module",
            {
                "entity_type": "user",
                "entity_id": "eid-1",
                "old_state": "pending",
                "new_state": "active",
            },
        ),
        (
            "missing_entity_type",
            {"module": "auth", "entity_id": "eid-1", "old_state": "pending", "new_state": "active"},
        ),
        (
            "none_values",
            {
                "module": None,
                "entity_type": None,
                "entity_id": None,
                "old_state": None,
                "new_state": None,
            },
        ),
    ]

    for mod in ["auth"]:  # Test one representative module for mutation cases
        store, ST = make_fresh_store(mod)

        for case_name, payload in cases:
            captured_events = []

            async def fake_publish(event, _captured=captured_events):
                _captured.append(event)

            from src.events.bus import event_bus

            original_publish = event_bus.publish
            event_bus.publish = fake_publish

            try:
                if payload is None:
                    action = ST()
                else:
                    action = ST(payload)
                await store.dispatch(action)
                await asyncio.sleep(0.05)
                report(
                    PASS, f"test_mutation_empty[{case_name}]", f"No crash with payload={payload!r}"
                )
            except Exception as e:
                report(
                    FAIL,
                    f"test_mutation_empty[{case_name}]",
                    "CRASH with empty/None fields — store is not robust",
                    expected="No exception",
                    actual=f"{type(e).__name__}: {e}",
                )
            finally:
                event_bus.publish = original_publish


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Mutation — invalid/impossible state combo
# ─────────────────────────────────────────────────────────────────────────────


async def test_mutation_invalid_state_combo():
    """Dispatch StateTransitioned with impossible states — must NOT crash the store."""
    captured_events = []

    async def fake_publish(event, _captured=captured_events):
        _captured.append(event)

    from src.events.bus import event_bus

    original_publish = event_bus.publish
    event_bus.publish = fake_publish

    try:
        store, ST = make_fresh_store("auth")
        action = ST(
            module="auth",
            entity_type="user",
            entity_id="eid-001",
            old_state="banned",  # invalid: banned → pending is not an FSM transition
            new_state="pending",
        )
        await store.dispatch(action)
        await asyncio.sleep(0.05)
        report(
            PASS,
            "test_mutation_invalid_state_combo",
            "Store did not crash on impossible state combo (banned→pending)",
        )
    except Exception as e:
        report(
            FAIL,
            "test_mutation_invalid_state_combo",
            "Store crashed on impossible state combo",
            expected="No exception (store accepts any state strings)",
            actual=f"{type(e).__name__}: {e}",
        )
    finally:
        event_bus.publish = original_publish


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Effect error handling — broken EventBus must NOT propagate
# ─────────────────────────────────────────────────────────────────────────────


async def test_effect_error_handling():
    """If EventBus.publish raises, store.dispatch must NOT raise to caller."""

    async def exploding_publish(event):
        raise RuntimeError("SIMULATED EVENTBUS FAILURE")

    from src.events.bus import event_bus

    original_publish = event_bus.publish
    event_bus.publish = exploding_publish

    try:
        store, ST = make_fresh_store("auth")
        action = ST(
            module="auth",
            entity_type="user",
            entity_id="eid-err",
            old_state="pending",
            new_state="active",
        )
        await store.dispatch(action)
        await asyncio.sleep(0.05)
        report(
            PASS,
            "test_effect_error_handling",
            "store.dispatch did not raise when EventBus.publish explodes",
        )
    except Exception as e:
        report(
            FAIL,
            "test_effect_error_handling",
            "store.dispatch raised when EventBus.publish exploded (bad: caller should be shielded)",
            expected="No exception from dispatch",
            actual=f"{type(e).__name__}: {e}",
        )
    finally:
        event_bus.publish = original_publish


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Verify source is NOT {module}.fsm (it changed to {module}.store)
# Compare old emit_state_changed vs new publish_state_changed
# ─────────────────────────────────────────────────────────────────────────────


async def test_source_changed_from_fsm_to_store():
    """
    OLD: source = f"{module}.fsm"
    NEW: source = f"{module}.store"
    This is an intentional change, but it BREAKS backward compatibility.
    Downstream consumers that subscribe on source == "{module}.fsm" will miss events.
    Test reports this as a DOCUMENTED DISCREPANCY.
    """
    captured_events = []

    async def fake_publish(event, _captured=captured_events):
        _captured.append(event)

    from src.events.bus import event_bus

    original_publish = event_bus.publish
    event_bus.publish = fake_publish

    try:
        store, ST = make_fresh_store("auth")
        action = ST(
            module="auth",
            entity_type="user",
            entity_id="eid-src",
            old_state="pending",
            new_state="active",
        )
        await store.dispatch(action)
        await asyncio.sleep(0.05)
    finally:
        event_bus.publish = original_publish

    sc_events = [e for e in captured_events if e.type.endswith(".state_changed")]
    if not sc_events:
        report(
            FAIL,
            "test_source_fsm_vs_store",
            "No state_changed event emitted for source check",
            actual="(no events)",
        )
        return

    evt = sc_events[0]
    old_source = "auth.fsm"
    new_source = "auth.store"

    if evt.source == new_source:
        # Source changed — it's intentional but breaking
        report(
            FAIL,
            "test_source_fsm_vs_store",
            "SOURCE CHANGED from .fsm to .store — BACKWARD COMPAT BREAK: "
            "downstream consumers filtering on source='auth.fsm' will miss events",
            expected=f"source='{old_source}' (old emit_state_changed)",
            actual=f"source='{evt.source}' (new publish_state_changed effect)",
        )
    elif evt.source == old_source:
        report(
            PASS,
            "test_source_fsm_vs_store",
            "Source preserved as {module}.fsm (backward compatible)",
        )
    else:
        report(
            FAIL,
            "test_source_fsm_vs_store",
            "Unexpected source value",
            expected=f"'{old_source}' or '{new_source}'",
            actual=f"'{evt.source}'",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: briefing publish_state_changed DROPS extra payload fields
#         (no **extra spread like auth/taskflow/nodeflow)
# ─────────────────────────────────────────────────────────────────────────────


async def test_briefing_drops_extra_fields():
    """
    briefing publish_state_changed does NOT spread extra payload keys into data,
    while auth/taskflow/nodeflow DO spread them.
    This is an inconsistency — extra context fields are silently lost in briefing.
    """
    captured_events = []

    async def fake_publish(event, _captured=captured_events):
        _captured.append(event)

    from src.events.bus import event_bus

    original_publish = event_bus.publish
    event_bus.publish = fake_publish

    try:
        from src.modules.briefing.store import StateTransitioned, briefing_store

        action = StateTransitioned(
            module="briefing",
            entity_type="daily",
            entity_id="daily-001",
            old_state="pending",
            new_state="completed",
            user_id="uid-100",
            extra_context="should_appear_in_data",  # extra field
        )
        await briefing_store.dispatch(action)
        await asyncio.sleep(0.05)
    finally:
        event_bus.publish = original_publish

    sc_events = [e for e in captured_events if e.type.endswith(".state_changed")]
    if not sc_events:
        report(
            FAIL,
            "test_briefing_extra_fields",
            "No state_changed event emitted",
            actual="(no events)",
        )
        return

    evt = sc_events[0]
    if "extra_context" in evt.data:
        report(
            PASS,
            "test_briefing_extra_fields",
            "briefing passes extra fields into event data (consistent with auth/taskflow)",
        )
    else:
        report(
            FAIL,
            "test_briefing_extra_fields",
            "briefing.publish_state_changed DROPS extra payload fields — INCONSISTENT with auth/taskflow/nodeflow",
            expected="data contains 'extra_context' key",
            actual=f"data keys: {list(evt.data.keys())}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: finance publish_state_changed DROPS extra payload fields
#          (same issue as briefing)
# ─────────────────────────────────────────────────────────────────────────────


async def test_finance_drops_extra_fields():
    """
    finance publish_state_changed also does NOT spread extra payload keys,
    unlike auth/taskflow/nodeflow.
    """
    captured_events = []

    async def fake_publish(event, _captured=captured_events):
        _captured.append(event)

    from src.events.bus import event_bus

    original_publish = event_bus.publish
    event_bus.publish = fake_publish

    try:
        from src.modules.finance.store import StateTransitioned, finance_store

        action = StateTransitioned(
            module="finance",
            entity_type="installment",
            entity_id="inst-001",
            old_state="active",
            new_state="completed",
            user_id="uid-200",
            reason="paid_off",  # extra field
        )
        await finance_store.dispatch(action)
        await asyncio.sleep(0.05)
    finally:
        event_bus.publish = original_publish

    sc_events = [e for e in captured_events if e.type.endswith(".state_changed")]
    if not sc_events:
        report(
            FAIL,
            "test_finance_extra_fields",
            "No state_changed event emitted",
            actual="(no events)",
        )
        return

    evt = sc_events[0]
    if "reason" in evt.data:
        report(
            PASS,
            "test_finance_extra_fields",
            "finance passes extra fields into event data (consistent with auth/taskflow)",
        )
    else:
        report(
            FAIL,
            "test_finance_extra_fields",
            "finance.publish_state_changed DROPS extra payload fields — INCONSISTENT with auth/taskflow/nodeflow",
            expected="data contains 'reason' key",
            actual=f"data keys: {list(evt.data.keys())}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: FeatureStore dispatch also publishes to EventBus via publish_fire_and_forget
#          with type=action.type (e.g. "auth.state.transitioned"), NOT the state_changed type
#          This means TWO events are published per dispatch — one is the action event,
#          one is the state_changed event from the effect.
# ─────────────────────────────────────────────────────────────────────────────


async def test_double_publish():
    """
    FeatureStore.dispatch always calls publish_fire_and_forget(Event(type=action.type, ...))
    AND the StateTransitioned effect calls event_bus.publish(Event(type=...state_changed...)).
    This means 2 events are published per dispatch.

    Verify: both events arrive and confirm dual-publish behavior.
    The fire-and-forget publishes type="auth.state.transitioned" (the action type).
    The effect publishes type="auth.user.state_changed".
    """
    captured_events = []

    async def fake_publish(event, _captured=captured_events):
        _captured.append(event)

    from src.events.bus import event_bus

    original_publish = event_bus.publish
    event_bus.publish = fake_publish

    # Also patch publish_fire_and_forget to use our fake
    def fake_fire_and_forget(event, _captured=captured_events):
        _captured.append(event)

    original_fnf = event_bus.publish_fire_and_forget
    event_bus.publish_fire_and_forget = fake_fire_and_forget

    try:
        store, ST = make_fresh_store("auth")
        action = ST(
            module="auth",
            entity_type="user",
            entity_id="eid-double",
            old_state="pending",
            new_state="active",
        )
        await store.dispatch(action)
        await asyncio.sleep(0.05)
    finally:
        event_bus.publish = original_publish
        event_bus.publish_fire_and_forget = original_fnf

    action_events = [e for e in captured_events if e.type == "auth.state.transitioned"]
    state_changed_events = [e for e in captured_events if e.type.endswith(".state_changed")]

    if action_events and state_changed_events:
        report(
            PASS,
            "test_double_publish",
            f"Both action event ({action_events[0].type!r}) and "
            f"state_changed event ({state_changed_events[0].type!r}) published",
        )
    elif not action_events:
        report(
            FAIL,
            "test_double_publish",
            "Action event (type='auth.state.transitioned') NOT published via fire-and-forget",
            expected="Event with type='auth.state.transitioned'",
            actual=f"Events: {[e.type for e in captured_events]}",
        )
    elif not state_changed_events:
        report(
            FAIL,
            "test_double_publish",
            "state_changed effect event NOT published",
            expected="Event ending with '.state_changed'",
            actual=f"Events: {[e.type for e in captured_events]}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: Verify old emit_state_changed format vs new publish_state_changed
#          Document exact structural parity check
# ─────────────────────────────────────────────────────────────────────────────


async def test_format_parity_with_old_emit_state_changed():
    """
    Old emit_state_changed format:
      type   = "{module}.{entity_type}.state_changed"
      data   = {"entity_id": ..., "old_state": ..., "new_state": ..., **extra}
      source = "{module}.fsm"
      user_id = user_id

    New publish_state_changed format:
      type   = "{module}.{entity_type}.state_changed"   ✓ same
      data   = {"entity_id": ..., "old_state": ..., "new_state": ..., **extra (only some modules)}
      source = "{module}.store"                          ✗ DIFFERENT
      user_id = user_id                                  ✓ same

    Additional observation: old emit_state_changed was called with `extra` dict.
    New approach passes extra via payload spread — but only auth/taskflow/nodeflow do this.
    briefing and finance LOSE extra fields.
    """
    # This test documents the format comparison
    from src.shared.fsm import emit_state_changed

    captured_old = []
    captured_new = []

    async def capture_old(event, _c=captured_old):
        _c.append(event)

    async def capture_new(event, _c=captured_new):
        _c.append(event)

    from src.events.bus import event_bus

    original_publish = event_bus.publish

    # Capture old format
    event_bus.publish = capture_old
    await emit_state_changed(
        module="auth",
        entity_type="user",
        entity_id="eid-parity",
        old_state="pending",
        new_state="active",
        user_id="uid-parity",
        extra={"reason": "admin_activation"},
    )

    # Capture new format (auth store with all extra spread)
    event_bus.publish = capture_new
    from src.modules.auth.store import StateTransitioned, auth_store

    def fake_fire_and_forget(event):
        pass  # ignore the action event

    original_fnf = event_bus.publish_fire_and_forget
    event_bus.publish_fire_and_forget = fake_fire_and_forget

    try:
        action = StateTransitioned(
            module="auth",
            entity_type="user",
            entity_id="eid-parity",
            old_state="pending",
            new_state="active",
            user_id="uid-parity",
            reason="admin_activation",  # extra field — spread via **extra in auth
        )
        await auth_store.dispatch(action)
        await asyncio.sleep(0.05)
    finally:
        event_bus.publish = original_publish
        event_bus.publish_fire_and_forget = original_fnf

    if not captured_old or not captured_new:
        report(FAIL, "test_format_parity", "Could not capture events for comparison")
        return

    old_evt = captured_old[0]
    new_sc = [e for e in captured_new if e.type.endswith(".state_changed")]
    if not new_sc:
        report(
            FAIL,
            "test_format_parity",
            "No state_changed event from new publish_state_changed",
            actual=f"Events captured: {[e.type for e in captured_new]}",
        )
        return

    new_evt = new_sc[0]

    differences = []
    if old_evt.type != new_evt.type:
        differences.append(f"type: old={old_evt.type!r} new={new_evt.type!r}")
    if old_evt.data != new_evt.data:
        differences.append(f"data: old={old_evt.data} new={new_evt.data}")
    if old_evt.source != new_evt.source:
        differences.append(f"source: old={old_evt.source!r} new={new_evt.source!r}")
    if old_evt.user_id != new_evt.user_id:
        differences.append(f"user_id: old={old_evt.user_id!r} new={new_evt.user_id!r}")

    if differences:
        report(
            FAIL,
            "test_format_parity",
            "Old emit_state_changed vs new publish_state_changed DIFFER",
            expected="Identical events",
            actual="\n    " + "\n    ".join(differences),
        )
    else:
        report(PASS, "test_format_parity", "Old and new event formats are identical")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


async def main():
    print("=" * 70)
    print("FSM→Store Integration Tests (Independent Tester — Six Iron Rules)")
    print("=" * 70)
    print()

    print("── Test 1: StateTransitioned exists in all 5 modules ───────────────")
    await test_state_transitioned_exists_in_all_modules()
    print()

    print("── Test 2: Schema invariant vs old emit_state_changed ──────────────")
    await test_schema_invariant_vs_emit_state_changed()
    print()

    print("── Test 3: user_id passthrough ─────────────────────────────────────")
    await test_user_id_passthrough()
    print()

    print("── Test 4: No-op reducer ────────────────────────────────────────────")
    await test_noop_reducer()
    print()

    print("── Test 5: Mutation — empty/None fields ─────────────────────────────")
    await test_mutation_empty_fields()
    print()

    print("── Test 6: Mutation — invalid state combo ───────────────────────────")
    await test_mutation_invalid_state_combo()
    print()

    print("── Test 7: Effect error handling (broken EventBus) ──────────────────")
    await test_effect_error_handling()
    print()

    print("── Test 8: Source changed .fsm → .store (backward compat) ──────────")
    await test_source_changed_from_fsm_to_store()
    print()

    print("── Test 9: briefing drops extra payload fields ───────────────────────")
    await test_briefing_drops_extra_fields()
    print()

    print("── Test 10: finance drops extra payload fields ───────────────────────")
    await test_finance_drops_extra_fields()
    print()

    print("── Test 11: Double-publish (action + state_changed) ─────────────────")
    await test_double_publish()
    print()

    print("── Test 12: Full format parity with old emit_state_changed ──────────")
    await test_format_parity_with_old_emit_state_changed()
    print()

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r[0] == PASS)
    failed = total - passed

    print("=" * 70)
    print(f"SUMMARY: {passed}/{total} passed, {failed} failed")
    print("=" * 70)

    if failed > 0:
        print("\nFAILED TESTS:")
        for r in results:
            if r[0] == FAIL:
                print(f"  ❌ {r[1]} — {r[2]}")
                if r[3]:
                    print(f"     Expected: {r[3]}")
                if r[4]:
                    print(f"     Actual:   {r[4]}")
    print()
    return failed


if __name__ == "__main__":
    failed = asyncio.run(main())
    sys.exit(1 if failed > 0 else 0)
