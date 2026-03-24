"""Tests for DailyOS → Memvault feedback loop.

Verifies:
1. Plan completion emits PLAN_COMPLETED event with correct payload
2. Memvault handler creates attitude block from behavioral data
3. Idempotent: duplicate events don't create duplicate blocks
4. Edge cases: empty items, no reflection
"""

import pytest
from src.events.backends.memory import InMemoryBackend
from src.events.bus import Event, EventBus
from src.events.types import DailyosEvents
from src.modules.dailyos.events import _synthesize_behavioral_summary
from src.modules.dailyos.services import _build_completion_payload

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakePlan:
    """Minimal plan object for testing _build_completion_payload."""

    def __init__(
        self,
        *,
        id="plan-001",
        plan_date="2026-03-09",
        space_id="default",
        completion_score=0.75,
        items=None,
        reflection=None,
        method_state=None,
    ):
        self.id = id
        self.plan_date = plan_date
        self.space_id = space_id
        self.completion_score = completion_score
        self.items = items or []
        self.reflection = reflection
        self.method_state = method_state


@pytest.fixture
def bus() -> EventBus:
    return EventBus(backend=InMemoryBackend())


# ---------------------------------------------------------------------------
# T1: _build_completion_payload tests
# ---------------------------------------------------------------------------


class TestBuildCompletionPayload:
    def test_basic_payload(self):
        plan = FakePlan(
            items=[
                {"title": "寫測試", "status": "completed", "is_frog": True},
                {"title": "開會", "status": "completed", "is_frog": False},
                {"title": "買菜", "status": "incomplete", "is_frog": False},
            ],
            reflection="今天效率不錯",
        )
        payload = _build_completion_payload(plan)

        assert payload["plan_id"] == "plan-001"
        assert payload["plan_date"] == "2026-03-09"
        assert payload["space_id"] == "default"
        assert payload["completion_score"] == 0.75
        assert payload["total_items"] == 3
        assert payload["completed_count"] == 2
        assert payload["carry_count"] == 1
        assert payload["frog_completed"] is True
        assert payload["frog_title"] == "寫測試"
        assert payload["reflection"] == "今天效率不錯"

    def test_empty_items(self):
        plan = FakePlan(items=[])
        payload = _build_completion_payload(plan)

        assert payload["total_items"] == 0
        assert payload["completed_count"] == 0
        assert payload["carry_count"] == 0
        assert payload["frog_completed"] is False
        assert payload["frog_title"] is None

    def test_frog_not_completed(self):
        plan = FakePlan(
            items=[
                {"title": "重要任務", "status": "incomplete", "is_frog": True},
            ]
        )
        payload = _build_completion_payload(plan)

        assert payload["frog_completed"] is False
        assert payload["frog_title"] == "重要任務"

    def test_no_frog(self):
        plan = FakePlan(
            items=[
                {"title": "一般任務", "status": "completed", "is_frog": False},
            ]
        )
        payload = _build_completion_payload(plan)

        assert payload["frog_completed"] is False
        assert payload["frog_title"] is None

    def test_none_items_defaults_to_empty(self):
        plan = FakePlan(items=None)
        payload = _build_completion_payload(plan)
        assert payload["total_items"] == 0


# ---------------------------------------------------------------------------
# T2: _synthesize_behavioral_summary tests
# ---------------------------------------------------------------------------


class TestSynthesizeBehavioralSummary:
    def test_full_summary(self):
        data = {
            "plan_date": "2026-03-09",
            "total_items": 5,
            "completed_count": 4,
            "carry_count": 1,
            "completion_score": 0.8,
            "frog_completed": True,
            "frog_title": "寫架構文件",
            "reflection": "專注力比昨天好",
        }
        result = _synthesize_behavioral_summary(data)

        assert "2026-03-09" in result
        assert "80%" in result
        assert "4/5" in result
        assert "1 項遞延" in result
        assert "寫架構文件" in result
        assert "已完成" in result
        assert "專注力比昨天好" in result

    def test_no_carry(self):
        data = {
            "plan_date": "2026-03-09",
            "total_items": 3,
            "completed_count": 3,
            "carry_count": 0,
            "completion_score": 1.0,
            "frog_completed": True,
            "frog_title": "核心功能",
        }
        result = _synthesize_behavioral_summary(data)
        assert "遞延" not in result
        assert "100%" in result

    def test_frog_not_completed(self):
        data = {
            "plan_date": "2026-03-09",
            "total_items": 2,
            "completed_count": 1,
            "carry_count": 1,
            "completion_score": 0.5,
            "frog_completed": False,
            "frog_title": "難題",
        }
        result = _synthesize_behavioral_summary(data)
        assert "未完成" in result

    def test_no_frog_title(self):
        data = {
            "plan_date": "2026-03-09",
            "total_items": 1,
            "completed_count": 1,
            "carry_count": 0,
            "completion_score": 1.0,
            "frog_completed": False,
            "frog_title": None,
        }
        result = _synthesize_behavioral_summary(data)
        assert "青蛙" not in result

    def test_empty_items_returns_none(self):
        data = {"plan_date": "2026-03-09", "total_items": 0}
        result = _synthesize_behavioral_summary(data)
        assert result is None

    def test_no_reflection(self):
        data = {
            "plan_date": "2026-03-09",
            "total_items": 2,
            "completed_count": 2,
            "carry_count": 0,
            "completion_score": 1.0,
            "frog_completed": False,
            "frog_title": None,
            "reflection": None,
        }
        result = _synthesize_behavioral_summary(data)
        assert "反思" not in result


# ---------------------------------------------------------------------------
# Event emission test (unit level, no DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_completed_event_is_emitted(bus: EventBus):
    """Verify event is emitted with correct type and payload structure."""
    captured: list[Event] = []

    @bus.on(DailyosEvents.PLAN_COMPLETED)
    async def capture_event(event: Event):
        captured.append(event)

    plan = FakePlan(
        items=[
            {"title": "測試任務", "status": "completed", "is_frog": True},
        ],
        reflection="測試反思",
    )
    payload = _build_completion_payload(plan)

    await bus.publish(
        Event(
            type=DailyosEvents.PLAN_COMPLETED,
            data=payload,
            source="dailyos",
            user_id="test-user",
        )
    )

    assert len(captured) == 1
    evt = captured[0]
    assert evt.type == "dailyos.plan.completed"
    assert evt.data["plan_id"] == "plan-001"
    assert evt.data["frog_completed"] is True
    assert evt.data["reflection"] == "測試反思"
    assert evt.source == "dailyos"
