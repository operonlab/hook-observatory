"""Tests for the notification channel system.

Covers:
  - Capability detection (has_capability / get_capabilities)
  - Severity / icon mapping on concrete channels
  - Channel registry: auto-discovery, lookup, list, register, reset
  - Channel send behaviour (unconfigured / error paths, mock HTTP)
  - BaseChannel contract enforcement
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure core/src is importable (mirrors conftest.py pattern)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Imports — all done at module level so missing deps cause collection failures,
# not silently skipped tests (Zero Compromise policy).
# ---------------------------------------------------------------------------

from src.modules.notification.channels.base import BaseChannel
from src.modules.notification.channels.registry import (
    discover_channels,
    get_channel,
    list_channels,
    register_channel,
    reset_registry,
)
from src.shared.capabilities import (
    SupportsGrouping,
    SupportsIcon,
    SupportsPriority,
    get_capabilities,
    has_capability,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_registry():
    """Reset the channel registry before every test for full isolation."""
    reset_registry()
    yield
    reset_registry()


def _make_bark():
    """Import and return a fresh BarkChannel instance."""
    from src.modules.notification.channels.bark_channel import BarkChannel
    return BarkChannel()


def _make_web_push():
    from src.modules.notification.channels.web_push_channel import WebPushChannel
    return WebPushChannel()


# ===========================================================================
# 1. Capability Detection Tests
# ===========================================================================

class TestCapabilities:

    def test_has_capability_positive(self):
        """BarkChannel implements SupportsGrouping — has_capability returns True."""
        bark = _make_bark()
        assert has_capability(bark, SupportsGrouping) is True

    def test_has_capability_negative(self):
        """WebPushChannel does NOT implement SupportsPriority — returns False."""
        wp = _make_web_push()
        assert has_capability(wp, SupportsPriority) is False

    def test_get_capabilities_mixed(self):
        """get_capabilities returns correct bool dict for multiple checks."""
        bark = _make_bark()
        result = get_capabilities(bark, SupportsGrouping, SupportsPriority, SupportsIcon)
        assert result[SupportsGrouping] is True
        assert result[SupportsPriority] is True
        assert result[SupportsIcon] is False

    def test_get_capabilities_web_push(self):
        """WebPushChannel supports Icon but not Priority or Grouping."""
        wp = _make_web_push()
        result = get_capabilities(wp, SupportsGrouping, SupportsPriority, SupportsIcon)
        assert result[SupportsGrouping] is False
        assert result[SupportsPriority] is False
        assert result[SupportsIcon] is True

    def test_bark_map_severity_critical(self):
        """Bark maps 'critical' → 'timeSensitive'."""
        bark = _make_bark()
        assert bark.map_severity("critical") == "timeSensitive"

    def test_bark_map_severity_info(self):
        """Bark maps 'info' → 'active'."""
        bark = _make_bark()
        assert bark.map_severity("info") == "active"

    def test_bark_map_severity_warning(self):
        """Bark maps 'warning' → 'timeSensitive'."""
        bark = _make_bark()
        assert bark.map_severity("warning") == "timeSensitive"

    def test_bark_map_severity_unknown_falls_back(self):
        """Bark returns 'active' for unknown severity strings."""
        bark = _make_bark()
        assert bark.map_severity("unknown_level") == "active"

    def test_web_push_icon_known_category(self):
        """WebPush returns category-specific icon for known categories."""
        wp = _make_web_push()
        assert wp.get_icon_url("finance") == "/icons/finance-192.png"
        assert wp.get_icon_url("taskflow") == "/icons/taskflow-192.png"
        assert wp.get_icon_url("intelflow") == "/icons/intelflow-192.png"

    def test_web_push_icon_unknown_category(self):
        """WebPush returns the default icon for unknown categories."""
        wp = _make_web_push()
        assert wp.get_icon_url("") == "/icons/icon-192.png"
        assert wp.get_icon_url("something_else") == "/icons/icon-192.png"

    def test_bark_get_group_passthrough(self):
        """BarkChannel.get_group returns category string as group name."""
        bark = _make_bark()
        assert bark.get_group("finance") == "finance"
        assert bark.get_group("") == ""


# ===========================================================================
# 2. Channel Registry Tests
# ===========================================================================

class TestChannelRegistry:

    def test_discover_finds_all_channels(self):
        """Auto-discovery finds bark and web_push channels (ntfy disabled)."""
        discover_channels()
        names = list_channels()
        assert "bark" in names
        assert "web_push" in names
        assert "ntfy" not in names

    def test_get_channel_by_name_bark(self):
        """get_channel('bark') returns a BarkChannel instance."""
        from src.modules.notification.channels.bark_channel import BarkChannel
        discover_channels()
        ch = get_channel("bark")
        assert ch is not None
        assert isinstance(ch, BarkChannel)

    def test_get_channel_by_name_web_push(self):
        """get_channel('web_push') returns a WebPushChannel instance."""
        from src.modules.notification.channels.web_push_channel import WebPushChannel
        discover_channels()
        ch = get_channel("web_push")
        assert ch is not None
        assert isinstance(ch, WebPushChannel)

    def test_get_channel_unknown(self):
        """get_channel returns None for an unregistered channel name."""
        discover_channels()
        assert get_channel("nonexistent_channel") is None

    def test_list_channels_sorted(self):
        """list_channels returns names in sorted alphabetical order."""
        discover_channels()
        names = list_channels()
        assert names == sorted(names)

    def test_list_channels_returns_list(self):
        """list_channels return type is list[str]."""
        discover_channels()
        result = list_channels()
        assert isinstance(result, list)
        assert all(isinstance(n, str) for n in result)

    def test_register_custom_channel(self):
        """Manually registering a custom channel makes it retrievable."""

        class PagerChannel(BaseChannel):
            name = "pager"

            async def _do_send(self, title, body, *, url="", severity="info", category=""):
                return True

        pager = PagerChannel()
        register_channel(pager)
        assert get_channel("pager") is pager

    def test_register_custom_channel_appears_in_list(self):
        """A manually registered custom channel appears in list_channels()."""

        class SmsChannel(BaseChannel):
            name = "sms"

            async def _do_send(self, title, body, *, url="", severity="info", category=""):
                return True

        register_channel(SmsChannel())
        assert "sms" in list_channels()

    def test_reset_registry_clears_all(self):
        """reset_registry clears all channels and resets discovery flag."""
        discover_channels()
        assert len(list_channels()) > 0
        reset_registry()
        # After reset the internal dict is empty; list_channels() triggers fresh discovery
        # We want to verify the state is truly reset — call the internal store directly.
        from src.modules.notification.channels import registry as reg_module
        assert len(reg_module._CHANNELS) == 0
        assert reg_module._discovered is False

    def test_reset_registry_allows_rediscovery(self):
        """After reset, list_channels() can discover channels again."""
        discover_channels()
        reset_registry()
        # Fresh list_channels call should re-discover successfully
        names = list_channels()
        assert "bark" in names

    def test_get_channel_triggers_discovery(self):
        """Calling get_channel before discover_channels still finds the channel."""
        # Registry is reset by fixture; do NOT call discover_channels first
        ch = get_channel("bark")
        assert ch is not None

    def test_list_channels_triggers_discovery(self):
        """Calling list_channels before discover_channels still works."""
        names = list_channels()
        assert "bark" in names


# ===========================================================================
# 3. Channel Send Tests (mock HTTP)
# ===========================================================================

class TestChannelSend:

    @pytest.mark.asyncio
    async def test_bark_send_not_configured(self):
        """Bark returns False when bark_server_url and bark_device_key are empty."""
        bark = _make_bark()
        with patch("src.modules.notification.channels.bark_channel.settings") as mock_settings:
            mock_settings.bark_server_url = ""
            mock_settings.bark_device_key = ""
            result = await bark.send("Title", "Body")
        assert result is False

    @pytest.mark.asyncio
    async def test_bark_send_configured_success(self):
        """Bark returns True when server is configured and HTTP call succeeds."""
        bark = _make_bark()
        bark_mod = "src.modules.notification.channels.bark_channel"
        with patch(f"{bark_mod}.settings") as mock_settings, \
             patch(f"{bark_mod}._send_bark_sync", return_value=True):
            mock_settings.bark_server_url = "http://bark.local"
            mock_settings.bark_device_key = "abc123"
            result = await bark.send("Hello", "World", severity="info", category="finance")
        assert result is True

    @pytest.mark.asyncio
    async def test_bark_send_configured_failure(self):
        """Bark returns False when the HTTP call fails (sync helper returns False)."""
        bark = _make_bark()
        bark_mod = "src.modules.notification.channels.bark_channel"
        with patch(f"{bark_mod}.settings") as mock_settings, \
             patch(f"{bark_mod}._send_bark_sync", return_value=False):
            mock_settings.bark_server_url = "http://bark.local"
            mock_settings.bark_device_key = "abc123"
            result = await bark.send("Title", "Body")
        assert result is False

    @pytest.mark.asyncio
    async def test_base_channel_error_handling(self):
        """BaseChannel.send catches exceptions from _do_send and returns False."""

        class BrokenChannel(BaseChannel):
            name = "broken"

            async def _do_send(self, title, body, *, url="", severity="info", category=""):
                raise RuntimeError("simulated network failure")

        ch = BrokenChannel()
        result = await ch.send("Boom", "Crash")
        assert result is False

    @pytest.mark.asyncio
    async def test_base_channel_error_does_not_propagate(self):
        """Exceptions inside _do_send are swallowed — no raise escapes send()."""

        class ExplodingChannel(BaseChannel):
            name = "exploding"

            async def _do_send(self, title, body, *, url="", severity="info", category=""):
                raise ValueError("boom")

        ch = ExplodingChannel()
        # Must not raise
        try:
            result = await ch.send("Title", "Body")
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"send() propagated exception: {exc}")
        assert result is False

    @pytest.mark.asyncio
    async def test_web_push_send_to_subscriptions_no_vapid(self):
        """WebPush returns (0, N) when VAPID private key is not configured."""
        wp = _make_web_push()
        subscriptions = [
            {"endpoint": "https://push.example.com/1", "p256dh": "key1", "auth": "auth1"},
            {"endpoint": "https://push.example.com/2", "p256dh": "key2", "auth": "auth2"},
        ]
        with patch("src.modules.notification.channels.web_push_channel.settings") as mock_settings:
            mock_settings.vapid_private_key = ""
            mock_settings.vapid_contact = "mailto:admin@example.com"
            delivered, failed = await wp.send_to_subscriptions(subscriptions, {"title": "Hi"})
        assert delivered == 0
        assert failed == 2

    @pytest.mark.asyncio
    async def test_web_push_single_send_always_false(self):
        """WebPushChannel._do_send (single-recipient no-op) always returns False."""
        wp = _make_web_push()
        # BaseChannel.send wraps _do_send; False result means send() also returns False
        result = await wp.send("Title", "Body")
        assert result is False

    @pytest.mark.asyncio
    async def test_web_push_send_to_subscriptions_empty_list(self):
        """send_to_subscriptions with empty list returns (0, 0) when VAPID configured."""
        wp = _make_web_push()
        wp_mod = "src.modules.notification.channels.web_push_channel"
        fake_key = "-----BEGIN EC PRIVATE KEY-----\nfake\n-----END EC PRIVATE KEY-----"
        with patch(f"{wp_mod}._load_vapid_private_key", return_value=fake_key):
            delivered, failed = await wp.send_to_subscriptions([], {"title": "Hi"})
        assert delivered == 0
        assert failed == 0


# ===========================================================================
# 4. BaseChannel Contract Tests
# ===========================================================================

class TestBaseChannelContract:

    def test_all_channels_have_name(self):
        """Every registered channel has a non-empty name string."""
        discover_channels()
        names = list_channels()
        assert len(names) > 0, "No channels discovered — check *_channel.py exports"
        for name in names:
            ch = get_channel(name)
            assert isinstance(ch.name, str), f"Channel {name!r}: name is not a str"
            assert ch.name != "", f"Channel {name!r}: name is empty"

    def test_all_channels_are_base_channel(self):
        """Every registered channel is an instance of BaseChannel."""
        discover_channels()
        names = list_channels()
        assert len(names) > 0, "No channels discovered"
        for name in names:
            ch = get_channel(name)
            assert isinstance(ch, BaseChannel), (
                f"Channel {name!r} is not a BaseChannel subclass: {type(ch)}"
            )

    def test_all_channels_name_matches_registry_key(self):
        """Each channel's .name attribute matches the key used in the registry."""
        discover_channels()
        names = list_channels()
        for key in names:
            ch = get_channel(key)
            assert ch.name == key, (
                f"Registry key {key!r} doesn't match channel.name {ch.name!r}"
            )

    def test_all_channels_implement_send(self):
        """Every registered channel has a callable send() method."""
        import inspect
        discover_channels()
        for name in list_channels():
            ch = get_channel(name)
            assert hasattr(ch, "send"), f"Channel {name!r} missing send()"
            assert inspect.iscoroutinefunction(ch.send), (
                f"Channel {name!r} send() is not a coroutine function"
            )


# ===========================================================================
# 5. Notification Dedup Tests
# ===========================================================================

class TestNotificationDedup:

    @pytest.mark.asyncio
    async def test_dedup_blocks_same_tag(self):
        """Same tag within TTL window → second call returns True (duplicate)."""
        from src.modules.notification.services import _is_duplicate

        mock_conn = AsyncMock()
        mock_conn.aclose = AsyncMock()

        with patch("src.modules.notification.services.settings") as mock_settings, \
             patch("redis.asyncio.from_url", return_value=mock_conn):
            mock_settings.notification_dedup_ttl = 300
            mock_settings.redis_url = "redis://localhost:6379/0"

            # First call: key doesn't exist → SET NX returns True (was set)
            mock_conn.set = AsyncMock(return_value=True)
            result1 = await _is_duplicate("test-tag")
            assert result1 is False  # not a duplicate

            # Second call: key exists → SET NX returns None
            mock_conn.set = AsyncMock(return_value=None)
            result2 = await _is_duplicate("test-tag")
            assert result2 is True  # duplicate

    @pytest.mark.asyncio
    async def test_dedup_different_tag_passes(self):
        """Different tags both pass (no dedup)."""
        from src.modules.notification.services import _is_duplicate

        mock_conn = AsyncMock()
        mock_conn.set = AsyncMock(return_value=True)  # key was set (new)
        mock_conn.aclose = AsyncMock()

        with patch("src.modules.notification.services.settings") as mock_settings, \
             patch("redis.asyncio.from_url", return_value=mock_conn):
            mock_settings.notification_dedup_ttl = 300
            mock_settings.redis_url = "redis://localhost:6379/0"

            result1 = await _is_duplicate("tag-a")
            result2 = await _is_duplicate("tag-b")
            assert result1 is False
            assert result2 is False

    @pytest.mark.asyncio
    async def test_dedup_no_tag_skips(self):
        """tag=None or empty string → skip dedup, return False."""
        from src.modules.notification.services import _is_duplicate

        with patch("src.modules.notification.services.settings") as mock_settings:
            mock_settings.notification_dedup_ttl = 300

            assert await _is_duplicate("") is False
            assert await _is_duplicate(None) is False

    @pytest.mark.asyncio
    async def test_dedup_redis_unavailable_fallback(self):
        """Redis connection failure → fallback to False (allow, don't drop)."""
        from src.modules.notification.services import _is_duplicate

        with patch("src.modules.notification.services.settings") as mock_settings, \
             patch("redis.asyncio.from_url", side_effect=ConnectionError("Redis down")):
            mock_settings.notification_dedup_ttl = 300
            mock_settings.redis_url = "redis://localhost:6379/0"

            result = await _is_duplicate("some-tag")
            assert result is False  # fail-open
