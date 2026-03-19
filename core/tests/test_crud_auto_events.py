"""Tests for BaseCRUDService auto-event publishing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.shared.services import BaseCRUDService


def _make_instance(**kwargs):
    """Create a mock ORM instance with given attributes."""
    instance = MagicMock()
    for k, v in kwargs.items():
        setattr(instance, k, v)
    # hasattr checks
    instance.__class__ = type("FakeModel", (), {})
    return instance


class TestAutoPublishEvent:
    """Test _auto_publish_event dispatches correctly based on event_types."""

    def test_no_event_types_does_nothing(self):
        """Empty event_types → no publish (backward compat)."""
        svc = BaseCRUDService()
        svc.audit_module = "test"
        svc.event_types = {}

        instance = _make_instance(id="abc", space_id="s1", created_by="u1")

        with patch("src.events.bus.event_bus") as mock_bus:
            svc._auto_publish_event("created", instance)
            mock_bus.publish_fire_and_forget.assert_not_called()

    def test_auto_publish_created(self):
        """event_types with 'created' → publishes on after_create."""
        svc = BaseCRUDService()
        svc.audit_module = "finance"
        svc.event_types = {"created": "finance.wallet.created"}

        instance = _make_instance(id="w1", space_id="s1", created_by="u1")

        with patch("src.events.bus.event_bus") as mock_bus:
            svc.after_create(instance)
            mock_bus.publish_fire_and_forget.assert_called_once()
            event = mock_bus.publish_fire_and_forget.call_args[0][0]
            assert event.type == "finance.wallet.created"
            assert event.data["id"] == "w1"
            assert event.data["space_id"] == "s1"
            assert event.source == "finance"
            assert event.user_id == "u1"

    def test_auto_publish_updated_with_changes(self):
        """after_update with non-empty changes → publishes."""
        svc = BaseCRUDService()
        svc.audit_module = "finance"
        svc.event_types = {"updated": "finance.wallet.updated"}

        instance = _make_instance(id="w1", space_id="s1", created_by="u1")
        changes = {"name": {"old": "A", "new": "B"}}

        with patch("src.events.bus.event_bus") as mock_bus:
            svc.after_update(instance, changes)
            mock_bus.publish_fire_and_forget.assert_called_once()
            event = mock_bus.publish_fire_and_forget.call_args[0][0]
            assert event.type == "finance.wallet.updated"
            assert event.data["changes"] == changes

    def test_auto_publish_updated_empty_changes_skipped(self):
        """after_update with empty changes → no publish."""
        svc = BaseCRUDService()
        svc.audit_module = "finance"
        svc.event_types = {"updated": "finance.wallet.updated"}

        instance = _make_instance(id="w1", space_id="s1", created_by="u1")

        with patch("src.events.bus.event_bus") as mock_bus:
            svc.after_update(instance, {})
            mock_bus.publish_fire_and_forget.assert_not_called()

    def test_auto_publish_deleted(self):
        """after_delete → publishes."""
        svc = BaseCRUDService()
        svc.audit_module = "taskflow"
        svc.event_types = {"deleted": "taskflow.task.deleted"}

        instance = _make_instance(id="t1", space_id="s1", created_by="u1")

        with patch("src.events.bus.event_bus") as mock_bus:
            svc.after_delete(instance)
            mock_bus.publish_fire_and_forget.assert_called_once()
            event = mock_bus.publish_fire_and_forget.call_args[0][0]
            assert event.type == "taskflow.task.deleted"

    def test_action_not_in_event_types_skipped(self):
        """event_types only has 'created' → after_delete does nothing."""
        svc = BaseCRUDService()
        svc.audit_module = "paper"
        svc.event_types = {"created": "paper.article.created"}

        instance = _make_instance(id="a1", space_id="s1", created_by="u1")

        with patch("src.events.bus.event_bus") as mock_bus:
            svc.after_delete(instance)
            mock_bus.publish_fire_and_forget.assert_not_called()


class TestBuildEventData:
    """Test _build_event_data field extraction."""

    def test_basic_id_and_space_id(self):
        svc = BaseCRUDService()
        svc.audit_module = "test"
        instance = _make_instance(id="x1", space_id="s1")

        data = svc._build_event_data(instance, "created")
        assert data == {"id": "x1", "space_id": "s1"}

    def test_event_id_alias(self):
        svc = BaseCRUDService()
        svc.audit_module = "test"
        svc.event_id_alias = "task_id"
        instance = _make_instance(id="t1", space_id="s1")

        data = svc._build_event_data(instance, "created")
        assert data["task_id"] == "t1"
        assert data["id"] == "t1"

    def test_event_fields_extraction(self):
        svc = BaseCRUDService()
        svc.audit_module = "test"
        svc.event_fields = ("title", "tags")
        instance = _make_instance(id="t1", space_id="s1", title="Hello", tags=["a", "b"])

        data = svc._build_event_data(instance, "created")
        assert data["title"] == "Hello"
        assert data["tags"] == ["a", "b"]

    def test_event_fields_serializes_values(self):
        """datetime/Decimal fields are serialized via _serialize_value."""
        from datetime import UTC, datetime
        from decimal import Decimal

        svc = BaseCRUDService()
        svc.audit_module = "test"
        svc.event_fields = ("amount", "created_at")
        dt = datetime(2026, 3, 19, 12, 0, 0, tzinfo=UTC)
        instance = _make_instance(id="x", space_id="s", amount=Decimal("42.50"), created_at=dt)

        data = svc._build_event_data(instance, "created")
        assert data["amount"] == "42.50"
        assert data["created_at"] == dt.isoformat()

    def test_updated_includes_changes(self):
        svc = BaseCRUDService()
        svc.audit_module = "test"
        instance = _make_instance(id="x", space_id="s")
        changes = {"name": {"old": "A", "new": "B"}}

        data = svc._build_event_data(instance, "updated", changes)
        assert data["changes"] == changes

    def test_created_does_not_include_changes(self):
        svc = BaseCRUDService()
        svc.audit_module = "test"
        instance = _make_instance(id="x", space_id="s")

        data = svc._build_event_data(instance, "created")
        assert "changes" not in data

    def test_no_space_id_on_instance(self):
        """Instance without space_id → data has no space_id key."""
        svc = BaseCRUDService()
        svc.audit_module = "test"
        instance = MagicMock(spec=[])
        instance.id = "x"

        data = svc._build_event_data(instance, "created")
        assert data == {"id": "x"}

    def test_event_fields_skip_duplicates(self):
        """If a field is already in data (e.g., 'id'), don't overwrite."""
        svc = BaseCRUDService()
        svc.audit_module = "test"
        svc.event_fields = ("id", "title")
        instance = _make_instance(id="x", space_id="s", title="T")

        data = svc._build_event_data(instance, "created")
        assert data["id"] == "x"
        assert data["title"] == "T"


class TestOverridePreservation:
    """Subclass override of after_create should take priority over auto-publish."""

    def test_override_suppresses_auto_publish(self):
        class CustomService(BaseCRUDService):
            audit_module = "custom"
            event_types = {"created": "custom.entity.created"}

            def after_create(self, instance):
                # Custom logic, no auto-publish
                pass

        svc = CustomService()
        instance = _make_instance(id="c1", space_id="s1", created_by="u1")

        with patch("src.events.bus.event_bus") as mock_bus:
            svc.after_create(instance)
            mock_bus.publish_fire_and_forget.assert_not_called()
