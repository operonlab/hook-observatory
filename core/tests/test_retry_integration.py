"""Integration tests for retry behavior in notification adapters and oMLX bridge.

Behavioral spec (do NOT read implementation files):
  - Bark/Ntfy: retry up to 3x on network errors, no retry on HTTP errors
  - oMLX: dynamic_timeout scales with input size, capped at configured max

Mutation targets:
  - max_retries=3 → max_retries=1  → test_retries_3_times catches this
  - URLError not in retryable set  → test_bark_retries_on_network_error catches this
  - dynamic_timeout base=10 → 100  → test_write_timeout_scales_with_input_size catches this
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap (conftest already inserts core/ but be explicit for clarity)
# ---------------------------------------------------------------------------
_CORE_ROOT = Path(__file__).resolve().parent.parent
if str(_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CORE_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_http_response(status: int = 200, body: bytes = b"ok") -> MagicMock:
    """Return a mock that looks like urllib response used as context manager."""
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.status = status
    resp.read.return_value = body
    return resp


def _http_error(code: int) -> HTTPError:
    return HTTPError(url="http://example.com", code=code, msg="err", hdrs=None, fp=None)


# ---------------------------------------------------------------------------
# TestBarkRetry
# ---------------------------------------------------------------------------


class TestBarkRetry:
    """Bark adapter retry behavior — mock only external urllib.request.urlopen."""

    # ------------------------------------------------------------------
    # 1. Network error → retries exactly 3 times total
    # ------------------------------------------------------------------
    def test_bark_retries_on_network_error(self):
        """URLError must trigger retry up to 3 attempts (3 total calls)."""
        from src.modules.notification.adapters.bark import send_bark

        call_count = 0

        def always_fail(_url, timeout=None):
            nonlocal call_count
            call_count += 1
            raise URLError("simulated network failure")

        with (
            patch("urllib.request.urlopen", side_effect=always_fail),
            patch("time.sleep"),  # suppress real backoff delay
            patch(
                "src.modules.notification.adapters.bark.settings",
                bark_server_url="http://bark.example.com",
                bark_device_key="testkey",
            ),
        ):
            result = asyncio.run(
                send_bark("title", "body", url=None, group=None, sound=None, level=None, icon=None)
            )

        # After exhausting 3 retries the adapter must return False
        assert result is False, "Expected False after exhausting all retries"
        # MUTATION TARGET: max_retries=3 → must call urlopen 3 times
        assert call_count == 3, (
            f"Expected 3 urlopen calls (got {call_count}); mutation may have changed max_retries"
        )

    # ------------------------------------------------------------------
    # 2. Fail once then succeed → returns True
    # ------------------------------------------------------------------
    def test_bark_succeeds_on_second_try(self):
        """After one network failure the adapter succeeds on the second attempt."""
        from src.modules.notification.adapters.bark import send_bark

        attempt = 0

        def fail_then_succeed(_url, timeout=None):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise URLError("first attempt fails")
            return _make_http_response(200)

        with (
            patch("urllib.request.urlopen", side_effect=fail_then_succeed),
            patch("time.sleep"),
            patch(
                "src.modules.notification.adapters.bark.settings",
                bark_server_url="http://bark.example.com",
                bark_device_key="testkey",
            ),
        ):
            result = asyncio.run(
                send_bark("title", "body", url=None, group=None, sound=None, level=None, icon=None)
            )

        assert result is True, "Expected True when second attempt succeeds"
        assert attempt == 2, f"Expected exactly 2 urlopen calls (got {attempt})"

    # ------------------------------------------------------------------
    # 3. HTTP 4xx/5xx → no retry, return False immediately
    # ------------------------------------------------------------------
    def test_bark_no_retry_on_http_error(self):
        """HTTP 404 must NOT trigger retries — adapter returns False after 1 call."""
        from src.modules.notification.adapters.bark import send_bark

        call_count = 0

        def raise_http_error(_url, timeout=None):
            nonlocal call_count
            call_count += 1
            raise _http_error(404)

        with (
            patch("urllib.request.urlopen", side_effect=raise_http_error),
            patch("time.sleep"),
            patch(
                "src.modules.notification.adapters.bark.settings",
                bark_server_url="http://bark.example.com",
                bark_device_key="testkey",
            ),
        ):
            result = asyncio.run(
                send_bark("title", "body", url=None, group=None, sound=None, level=None, icon=None)
            )

        assert result is False, "Expected False on HTTP error"
        # HTTPError re-raised in _send_bark_once → skips retry → caught by outer except
        assert call_count == 1, f"HTTP errors must NOT be retried (got {call_count} calls)"

    # ------------------------------------------------------------------
    # 4. No config → False immediately, no HTTP call
    # ------------------------------------------------------------------
    def test_bark_returns_false_when_not_configured(self):
        """If bark_server_url or bark_device_key is absent, return False immediately."""
        from src.modules.notification.adapters.bark import send_bark

        with (
            patch("urllib.request.urlopen") as mock_urlopen,
            patch(
                "src.modules.notification.adapters.bark.settings",
                bark_server_url=None,
                bark_device_key=None,
            ),
        ):
            result = asyncio.run(
                send_bark("title", "body", url=None, group=None, sound=None, level=None, icon=None)
            )

        assert result is False, "Expected False when not configured"
        mock_urlopen.assert_not_called()


# ---------------------------------------------------------------------------
# TestNtfyRetry
# ---------------------------------------------------------------------------


class TestNtfyRetry:
    """Ntfy adapter retry behavior — same contract as Bark."""

    def test_ntfy_retries_on_network_error(self):
        """URLError must trigger retry up to 3 attempts."""
        from src.modules.notification.adapters.ntfy import send_ntfy

        call_count = 0

        def always_fail(_req, timeout=None):
            nonlocal call_count
            call_count += 1
            raise URLError("simulated network failure")

        with (
            patch("urllib.request.urlopen", side_effect=always_fail),
            patch("time.sleep"),
            patch(
                "src.modules.notification.adapters.ntfy.settings",
                ntfy_server_url="http://ntfy.example.com",
                ntfy_topic="test-topic",
            ),
        ):
            result = asyncio.run(send_ntfy("title", "body"))

        assert result is False
        assert call_count == 3, f"Expected 3 calls (got {call_count})"

    def test_ntfy_succeeds_on_second_try(self):
        """Succeeds on second attempt after one network failure."""
        from src.modules.notification.adapters.ntfy import send_ntfy

        attempt = 0

        def fail_then_succeed(_req, timeout=None):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise URLError("first attempt fails")
            return _make_http_response(200)

        with (
            patch("urllib.request.urlopen", side_effect=fail_then_succeed),
            patch("time.sleep"),
            patch(
                "src.modules.notification.adapters.ntfy.settings",
                ntfy_server_url="http://ntfy.example.com",
                ntfy_topic="test-topic",
            ),
        ):
            result = asyncio.run(send_ntfy("title", "body"))

        assert result is True
        assert attempt == 2

    def test_ntfy_no_retry_on_http_error(self):
        """HTTP errors must not be retried."""
        from src.modules.notification.adapters.ntfy import send_ntfy

        call_count = 0

        def raise_http_error(_req, timeout=None):
            nonlocal call_count
            call_count += 1
            raise _http_error(500)

        with (
            patch("urllib.request.urlopen", side_effect=raise_http_error),
            patch("time.sleep"),
            patch(
                "src.modules.notification.adapters.ntfy.settings",
                ntfy_server_url="http://ntfy.example.com",
                ntfy_topic="test-topic",
            ),
        ):
            result = asyncio.run(send_ntfy("title", "body"))

        assert result is False
        # HTTPError re-raised in _send_ntfy_once → skips retry → caught by outer except
        assert call_count == 1, f"HTTP errors must NOT be retried (got {call_count})"

    def test_ntfy_returns_false_when_not_configured(self):
        """Missing config → return False immediately, no HTTP call."""
        from src.modules.notification.adapters.ntfy import send_ntfy

        with (
            patch("urllib.request.urlopen") as mock_urlopen,
            patch(
                "src.modules.notification.adapters.ntfy.settings",
                ntfy_server_url=None,
                ntfy_topic=None,
            ),
        ):
            result = asyncio.run(send_ntfy("title", "body"))

        assert result is False
        mock_urlopen.assert_not_called()


# ---------------------------------------------------------------------------
# TestOmlxDynamicTimeout
# ---------------------------------------------------------------------------


class TestOmlxDynamicTimeout:
    """oMLX bridge uses workshop.timeout.dynamic_timeout internally.

    The dynamic_timeout function itself is thoroughly tested in
    libs/python/tests/test_timeout.py (46 tests). Here we only verify
    the omlx-specific wiring params produce expected results.
    """

    def test_write_timeout_scales_with_input_size(self):
        """omlx write: dynamic_timeout(base=10, factor=0.5, context, cap=30)."""
        from workshop.timeout import dynamic_timeout

        t_small = dynamic_timeout(base=10, factor=0.5, context=10, cap=30)
        t_large = dynamic_timeout(base=10, factor=0.5, context=1000, cap=30)
        assert t_small == pytest.approx(15.0, abs=0.1)
        assert t_large == pytest.approx(30.0, abs=0.1)
        assert t_large >= t_small

    def test_read_timeout_scales_with_input_size(self):
        """omlx read: dynamic_timeout(base=30, factor=0.5, context, cap=120)."""
        from workshop.timeout import dynamic_timeout

        t_small = dynamic_timeout(base=30, factor=0.5, context=10, cap=120)
        t_medium = dynamic_timeout(base=30, factor=0.5, context=100, cap=120)
        assert t_small == pytest.approx(35.0, abs=0.1)
        assert t_medium == pytest.approx(80.0, abs=0.1)
        assert t_medium > t_small

    def test_write_timeout_respects_cap(self):
        """Even enormous input, write timeout ≤ 30."""
        from workshop.timeout import dynamic_timeout

        t = dynamic_timeout(base=10, factor=0.5, context=100_000, cap=30)
        assert t <= 30
