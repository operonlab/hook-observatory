"""Invest state management — FeatureStore for portfolio and trading."""

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── Actions ──────────────────────────────────────────────────────────────

TradeExecuted = create_action("invest.trade.executed")
DividendReceived = create_action("invest.dividend.received")
ValuationUpdated = create_action("invest.valuation.updated")
PositionOpened = create_action("invest.position.opened")
PositionClosed = create_action("invest.position.closed")
AccountCreated = create_action("invest.account.created")
AccountUpdated = create_action("invest.account.updated")

# ── Reducer ──────────────────────────────────────────────────────────────

invest_reducer = create_reducer(
    {"positions": {}, "accounts": {}, "trade_count": 0, "dividend_total": 0.0},
    on(
        PositionOpened,
        lambda s, a: update_in(
            s,
            ["positions", a.payload.get("id", "") if a.payload else ""],
            lambda _: a.payload,
        ),
    ),
    on(
        PositionClosed,
        lambda s, a: update_in(
            s,
            ["positions", a.payload.get("id", "") if a.payload else ""],
            lambda _: None,
        ),
    ),
    on(
        TradeExecuted,
        lambda s, a: s.set("trade_count", s["trade_count"] + 1),
    ),
    on(
        DividendReceived,
        lambda s, a: s.set(
            "dividend_total",
            s["dividend_total"] + (a.payload.get("amount", 0.0) if a.payload else 0.0),
        ),
    ),
    on(
        AccountCreated,
        lambda s, a: update_in(
            s,
            ["accounts", a.payload.get("id", "") if a.payload else ""],
            lambda _: a.payload,
        ),
    ),
    on(
        AccountUpdated,
        lambda s, a: update_in(
            s,
            ["accounts", a.payload.get("id", "") if a.payload else ""],
            lambda existing: {**(existing or {}), **(a.payload or {})},
        ),
    ),
    on(
        ValuationUpdated,
        lambda s, a: update_in(
            s,
            ["accounts", a.payload.get("account_id", "") if a.payload else ""],
            lambda existing: {
                **(existing or {}),
                "valuation": a.payload.get("valuation") if a.payload else None,
            },
        ),
    ),
)

# ── Store ─────────────────────────────────────────────────────────────────

invest_store: FeatureStore = FeatureStore("invest", invest_reducer)

# ── Selectors ─────────────────────────────────────────────────────────────

select_positions = create_selector(lambda s: dict(s["positions"]) if s["positions"] else {})

select_accounts = create_selector(lambda s: dict(s["accounts"]) if s["accounts"] else {})

select_invest_stats = create_selector(
    lambda s: {
        "trade_count": s["trade_count"],
        "dividend_total": s["dividend_total"],
        "open_positions": len([v for v in s["positions"].values() if v is not None]),
        "account_count": len(s["accounts"]),
    }
)
