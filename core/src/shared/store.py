"""NgRx-style FeatureStore — wraps EventBus with Store/Reducer/Effect facade.

Cannibalized from pystorex/store.py + effects.py — adapted to Workshop:
- No RxPy (uses Workshop EventBus + channel.subscribe_handler)
- No immutables.Map (plain dict state)
- FeatureStore per module (not global root store) — modular monolith
- async effects (Workshop is async-first)

Usage:
    from src.shared.store import FeatureStore, effect
    from src.shared.actions import create_action, create_reducer, on
    from src.shared.selectors import create_selector

    WalletCreated = create_action("finance.wallet.created")
    TransactionCreated = create_action("finance.transaction.created")

    finance_reducer = create_reducer(
        {"wallets": {}, "total_balance": 0},
        on(WalletCreated, lambda state, action: {
            **state,
            "wallets": {**state["wallets"], action.payload["id"]: action.payload},
        }),
    )

    finance_store = FeatureStore("finance", finance_reducer)

    # Dispatch (also publishes to EventBus)
    await finance_store.dispatch(WalletCreated(id="w1", name="Main", balance=1000))

    # Select (memoized)
    select_wallets = create_selector(lambda s: s["wallets"])
    wallets = finance_store.select(select_wallets)

    # Effect (separated side-effects)
    @effect(WalletCreated)
    async def notify_wallet(action, store):
        await notification_service.send(f"New wallet: {action.payload['name']}")
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.shared.actions import Action, ActionCreator, ReducerFn

logger = logging.getLogger(__name__)


# ── FeatureStore ─────────────────────────────────────────────────────────


class FeatureStore[S]:
    """Module-level state container — wraps EventBus with NgRx semantics.

    Each core module gets its own FeatureStore. No global root store
    (Workshop is a modular monolith — modules own their schemas).
    """

    def __init__(
        self,
        feature_key: str,
        reducer: ReducerFn,
        *,
        event_bus: Any | None = None,
    ) -> None:
        self.feature_key = feature_key
        self._reducer = reducer
        self._state: S = reducer.initial_state
        self._event_bus = event_bus
        self._effects: list[_EffectRegistration] = []
        self._listeners: list[Callable[[S, S], None]] = []

    def _get_event_bus(self):
        """Lazy EventBus resolution — avoids circular imports at module load."""
        if self._event_bus is None:
            from src.events.bus import event_bus
            self._event_bus = event_bus
        return self._event_bus

    # ── State ────────────────────────────────────────────────────────

    def get_state(self) -> S:
        """Get current state snapshot."""
        return self._state

    def select(self, selector: Callable[[S], Any]) -> Any:
        """Apply a (memoized) selector to current state."""
        return selector(self._state)

    # ── Dispatch ─────────────────────────────────────────────────────

    async def dispatch(self, action: Action) -> None:
        """Dispatch action → reducer → state update → EventBus publish.

        Flow:
        1. Run reducer (pure, sync) to compute new state
        2. Update internal state
        3. Notify state listeners
        4. Publish to EventBus (async, for cross-module effects)
        5. Run registered effects (async)
        """
        old_state = self._state
        new_state = self._reducer(old_state, action)

        if new_state is not old_state:
            self._state = new_state
            for listener in self._listeners:
                try:
                    listener(old_state, new_state)
                except Exception as e:
                    logger.warning(
                        "Store[%s] listener error: %s", self.feature_key, e,
                    )

        # Bridge to EventBus
        bus = self._get_event_bus()
        from src.events.bus import Event
        event = Event(
            type=action.type,
            data=action.payload
            if isinstance(action.payload, dict)
            else {"payload": action.payload},
            source=self.feature_key,
        )
        bus.publish_fire_and_forget(event)

        # Run effects
        for eff in self._effects:
            if eff.action_type == action.type or eff.action_type == "*":
                try:
                    result = await eff.handler(action, self)
                    if eff.dispatch and isinstance(result, Action):
                        await self.dispatch(result)
                except Exception as e:
                    logger.warning(
                        "Store[%s] effect %s error: %s",
                        self.feature_key, eff.name, e,
                    )

    def dispatch_sync(self, action: Action) -> None:
        """Sync dispatch — reducer + listeners, no EventBus, no effects.

        Useful for batch state initialization or testing.
        """
        old_state = self._state
        new_state = self._reducer(old_state, action)
        if new_state is not old_state:
            self._state = new_state
            for listener in self._listeners:
                try:
                    listener(old_state, new_state)
                except Exception as e:
                    logger.warning(
                        "Store[%s] listener error: %s",
                        self.feature_key, e,
                    )

    # ── Effects ──────────────────────────────────────────────────────

    def register_effect(self, registration: _EffectRegistration) -> None:
        self._effects.append(registration)

    # ── Listeners ────────────────────────────────────────────────────

    def on_change(self, listener: Callable[[S, S], None]) -> Callable:
        """Subscribe to state changes. Returns unsubscribe function."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    # ── Repr ─────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"FeatureStore({self.feature_key!r}, effects={len(self._effects)})"


# ── Effect Decorator ─────────────────────────────────────────────────────


class _EffectRegistration:
    __slots__ = ("action_type", "dispatch", "handler", "name")

    def __init__(self, action_type: str, handler: Callable, dispatch: bool, name: str):
        self.action_type = action_type
        self.handler = handler
        self.dispatch = dispatch
        self.name = name


def effect(
    action_creator_or_type: ActionCreator | str,
    *,
    dispatch: bool = False,
    store: FeatureStore | None = None,
):
    """Decorator to register an async effect handler.

    Usage:
        @effect(WalletCreated)
        async def sync_invest(action, store):
            wallet = await invest_service.sync(action.payload["wallet_id"])

        @effect(WalletCreated, dispatch=True)
        async def chain_effect(action, store):
            return InvestSynced(wallet_id=action.payload["wallet_id"])

    If store is provided, auto-registers. Otherwise, call
    store.register_effect() manually.
    """
    if isinstance(action_creator_or_type, str):
        action_type = action_creator_or_type
    else:
        action_type = action_creator_or_type.type

    def decorator(fn: Callable) -> Callable:
        reg = _EffectRegistration(
            action_type=action_type,
            handler=fn,
            dispatch=dispatch,
            name=fn.__name__,
        )
        fn._effect_registration = reg  # type: ignore[attr-defined]

        if store is not None:
            store.register_effect(reg)

        return fn

    return decorator


def register_effects(target_store: FeatureStore, *effect_fns: Callable) -> None:
    """Batch-register effect functions on a store.

    Usage:
        register_effects(finance_store, sync_invest, notify_wallet, log_action)
    """
    for fn in effect_fns:
        reg = getattr(fn, "_effect_registration", None)
        if reg is None:
            raise ValueError(f"{fn.__name__} is not decorated with @effect")
        target_store.register_effect(reg)
