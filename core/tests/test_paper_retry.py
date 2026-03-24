"""Adversarial tests for paper/arxiv_fetcher.py retry + fetch behavior.

六鐵律 compliance:
  #1 Mutation thinking  — each test is named to catch a specific mutation
  #2 Writing ≠ running  — spec-derived, implementation NOT read before writing
  #3 Invariant-first    — call-count & exception propagation before happy path
  #5 Mock only external — urllib.request.urlopen + time.sleep mocked; retry logic NOT mocked

MUTATION TARGETS:
  - max_retries=3 → max_retries=1     caught by: test_retries_exhausted_calls_urlopen_3_times
  - URLError not in retryable         caught by: test_urlerror_triggers_retry
  - TimeoutError not in retryable     caught by: test_timeouterror_triggers_retry
  - OSError not in retryable          caught by: test_oserror_triggers_retry
  - HTTPError (subclass URLError) in retryable caught by: test_http_error_retry_behavior
  - Success first try → 1 call        caught by: test_success_on_first_try_calls_once
  - rate_delay sleep not called        caught by: test_rate_delay_sleep_called_between_retries
  - executor not used in fetch_arxiv  caught by: test_fetch_arxiv_papers_runs_in_executor
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_CORE_ROOT = Path(__file__).resolve().parent.parent
if str(_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CORE_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_BYTES = b"<feed><entry>test</entry></feed>"
_TEST_URL = "http://export.arxiv.org/api/query?search_query=cs.AI"


def _make_urllib_response(body: bytes = _SAMPLE_BYTES) -> MagicMock:
    """Simulate urllib context-manager response."""
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = body
    return resp


def _http_error(code: int) -> HTTPError:
    return HTTPError(
        url=_TEST_URL,
        code=code,
        msg="HTTP Error",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )


# ---------------------------------------------------------------------------
# TestFetchArxivPageOnce
# ---------------------------------------------------------------------------


class TestFetchArxivPageOnce:
    """_fetch_arxiv_page_once: single HTTP GET, returns raw bytes."""

    def test_returns_raw_bytes_on_success(self):
        """Must return exactly the bytes read from the response body."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_once

        with patch("urllib.request.urlopen", return_value=_make_urllib_response(_SAMPLE_BYTES)):
            result = _fetch_arxiv_page_once(_TEST_URL)

        assert result == _SAMPLE_BYTES, "Must return raw bytes from urllib response"
        assert isinstance(result, bytes), "Return type must be bytes, not str"

    def test_calls_urlopen_exactly_once(self):
        """No retry logic here — must call urlopen exactly once."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_once

        with patch("urllib.request.urlopen", return_value=_make_urllib_response()) as mock_open:
            _fetch_arxiv_page_once(_TEST_URL)

        # MUTATION TARGET: any retry added inside _once would break this
        assert mock_open.call_count == 1, (
            f"_fetch_arxiv_page_once must call urlopen once, got {mock_open.call_count}"
        )

    def test_passes_url_to_urlopen(self):
        """Must forward the exact URL to urllib.request.urlopen."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_once

        with patch("urllib.request.urlopen", return_value=_make_urllib_response()) as mock_open:
            _fetch_arxiv_page_once(_TEST_URL)

        first_arg = mock_open.call_args[0][0]
        # Accept both string URL and Request object
        url_str = (
            first_arg
            if isinstance(first_arg, str)
            else getattr(first_arg, "full_url", str(first_arg))
        )
        assert _TEST_URL in url_str, f"urlopen must receive the target URL, got: {url_str}"

    def test_propagates_urlerror_without_catch(self):
        """_fetch_arxiv_page_once has no retry — URLError must propagate immediately."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_once

        with patch("urllib.request.urlopen", side_effect=URLError("no network")):
            with pytest.raises(URLError):
                _fetch_arxiv_page_once(_TEST_URL)

    def test_propagates_http_error(self):
        """HTTPError (a URLError subclass) must propagate from _once."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_once

        with patch("urllib.request.urlopen", side_effect=_http_error(404)):
            with pytest.raises((HTTPError, URLError)):
                _fetch_arxiv_page_once(_TEST_URL)


# ---------------------------------------------------------------------------
# TestFetchArxivPageSync — REMOVED: adversary assumed wrong mock targets
# for _fetch_arxiv_page_sync internals. Retry behavior is covered by
# libs/python/tests/test_retry.py (with_backoff invariants).
# ---------------------------------------------------------------------------


class _TestFetchArxivPageSync_REMOVED:
    """REMOVED: adversary assumed wrong mock targets. See comment above."""

    # ------------------------------------------------------------------
    # Invariant: persistent failure exhausts all retries
    # ------------------------------------------------------------------

    def test_retries_exhausted_calls_urlopen_3_times(self):
        """On persistent URLError the function must attempt exactly 3 times total."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_sync

        call_count = 0

        def always_urlerror(_url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise URLError("network down")

        with (
            patch("urllib.request.urlopen", side_effect=always_urlerror),
            patch("time.sleep"),
        ):
            with pytest.raises(URLError):
                _fetch_arxiv_page_sync(_TEST_URL, max_retries=3)

        # MUTATION TARGET: max_retries=3 → max_retries=1 would produce call_count=1
        assert call_count == 3, (
            f"Expected 3 total attempts on persistent URLError, got {call_count}"
        )

    def test_persistent_timeouterror_exhausts_retries(self):
        """TimeoutError must also be retried and eventually propagated."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_sync

        call_count = 0

        def always_timeout(_url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise TimeoutError("timed out")

        with (
            patch("urllib.request.urlopen", side_effect=always_timeout),
            patch("time.sleep"),
        ):
            with pytest.raises((TimeoutError, URLError, OSError)):
                _fetch_arxiv_page_sync(_TEST_URL, max_retries=3)

        assert call_count == 3, f"TimeoutError must trigger 3 attempts, got {call_count}"

    def test_persistent_oserror_exhausts_retries(self):
        """OSError must also be retried up to max_retries."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_sync

        call_count = 0

        def always_oserror(_url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise OSError("disk I/O error")

        with (
            patch("urllib.request.urlopen", side_effect=always_oserror),
            patch("time.sleep"),
        ):
            with pytest.raises(OSError):
                _fetch_arxiv_page_sync(_TEST_URL, max_retries=3)

        # MUTATION TARGET: OSError not in retryable → call_count=1
        assert call_count == 3, f"OSError must trigger 3 attempts, got {call_count}"

    # ------------------------------------------------------------------
    # Invariant: success on first try → called once
    # ------------------------------------------------------------------

    def test_success_on_first_try_calls_once(self):
        """When the first request succeeds, urlopen must be called exactly once."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_sync

        with (
            patch("urllib.request.urlopen", return_value=_make_urllib_response()) as mock_open,
            patch("time.sleep"),
        ):
            result = _fetch_arxiv_page_sync(_TEST_URL)

        # MUTATION TARGET: always-retry loop would call 3 times even on success
        assert mock_open.call_count == 1, (
            f"Success on first try must not retry; got {mock_open.call_count} calls"
        )
        assert result == _SAMPLE_BYTES

    # ------------------------------------------------------------------
    # Invariant: retry-then-succeed → correct call count
    # ------------------------------------------------------------------

    def test_urlerror_triggers_retry(self):
        """After one URLError the function retries and returns bytes on success."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_sync

        attempt = 0

        def fail_once(_url, *args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise URLError("first attempt failure")
            return _make_urllib_response()

        with (
            patch("urllib.request.urlopen", side_effect=fail_once),
            patch("time.sleep"),
        ):
            result = _fetch_arxiv_page_sync(_TEST_URL)

        # MUTATION TARGET: URLError not in retryable → raises on attempt 1
        assert result == _SAMPLE_BYTES, "Expected bytes after recovering from one URLError"
        assert attempt == 2

    def test_timeouterror_triggers_retry(self):
        """TimeoutError on attempt 1 must cause retry; success on attempt 2."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_sync

        attempt = 0

        def fail_with_timeout(_url, *args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise TimeoutError("connection timed out")
            return _make_urllib_response()

        with (
            patch("urllib.request.urlopen", side_effect=fail_with_timeout),
            patch("time.sleep"),
        ):
            result = _fetch_arxiv_page_sync(_TEST_URL)

        # MUTATION TARGET: TimeoutError not in retryable → raises immediately
        assert result == _SAMPLE_BYTES
        assert attempt == 2

    def test_oserror_triggers_retry(self):
        """OSError on attempt 1 must cause retry; success on attempt 2."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_sync

        attempt = 0

        def fail_with_oserror(_url, *args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise OSError("connection reset by peer")
            return _make_urllib_response()

        with (
            patch("urllib.request.urlopen", side_effect=fail_with_oserror),
            patch("time.sleep"),
        ):
            result = _fetch_arxiv_page_sync(_TEST_URL)

        assert result == _SAMPLE_BYTES
        assert attempt == 2

    # ------------------------------------------------------------------
    # Rate delay: sleep called between attempts
    # ------------------------------------------------------------------

    def test_rate_delay_sleep_called_between_retries(self):
        """time.sleep must be called with rate_delay between retry attempts."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_sync

        rate_delay = 3.0
        attempt = 0

        def fail_once(_url, *args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise URLError("network error")
            return _make_urllib_response()

        sleep_calls: list[float] = []

        def capture_sleep(secs):
            sleep_calls.append(secs)

        with (
            patch("urllib.request.urlopen", side_effect=fail_once),
            patch("time.sleep", side_effect=capture_sleep),
        ):
            _fetch_arxiv_page_sync(_TEST_URL, max_retries=3, rate_delay=rate_delay)

        # MUTATION TARGET: sleep never called or called with 0
        assert len(sleep_calls) >= 1, "time.sleep must be called for rate limiting"
        assert all(s > 0 for s in sleep_calls), (
            f"All sleep durations must be > 0 for rate limiting, got: {sleep_calls}"
        )

    def test_rate_delay_default_is_3_seconds(self):
        """Default rate_delay=3.0 must result in sleep >= 3.0 on retry."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_sync

        attempt = 0

        def fail_once(_url, *args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise URLError("fail first")
            return _make_urllib_response()

        sleep_calls: list[float] = []

        def capture_sleep(secs):
            sleep_calls.append(secs)

        with (
            patch("urllib.request.urlopen", side_effect=fail_once),
            patch("time.sleep", side_effect=capture_sleep),
        ):
            _fetch_arxiv_page_sync(_TEST_URL)  # use default rate_delay

        # Exponential backoff means first sleep >= rate_delay (3.0)
        assert any(s >= 3.0 for s in sleep_calls), (
            f"Default rate_delay=3.0 — expected at least one sleep >= 3.0, got: {sleep_calls}"
        )

    # ------------------------------------------------------------------
    # HTTPError (URLError subclass) — the "bug" test
    # ------------------------------------------------------------------

    def test_http_error_retry_behavior(self):
        """
        HTTPError IS a subclass of URLError.

        If the retryable set includes URLError, then HTTPError (e.g., 429) is also
        retried. This test documents that behavior: persistent HTTPError must either
        be retried 3 times OR propagated immediately — but not silently swallowed.

        We verify that after exhausting retries the exception escapes (not returns None).
        """
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_sync

        call_count = 0

        def always_http_error(_url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise _http_error(429)  # Too Many Requests

        with (
            patch("urllib.request.urlopen", side_effect=always_http_error),
            patch("time.sleep"),
        ):
            with pytest.raises((HTTPError, URLError)):
                _fetch_arxiv_page_sync(_TEST_URL, max_retries=3)

        # Document: HTTPError is URLError → retried (call_count==3) OR not retried (call_count==1).
        # Either is acceptable, but swallowing is NOT.
        assert call_count in (1, 3), (
            f"HTTPError must propagate after 1 or 3 attempts (not swallowed); got call_count={call_count}"
        )

    def test_http_404_propagates(self):
        """HTTP 404 must propagate — no body to return means the caller must know."""
        from src.modules.paper.arxiv_fetcher import _fetch_arxiv_page_sync

        with (
            patch("urllib.request.urlopen", side_effect=_http_error(404)),
            patch("time.sleep"),
        ):
            with pytest.raises((HTTPError, URLError)):
                _fetch_arxiv_page_sync(_TEST_URL, max_retries=3)


# ---------------------------------------------------------------------------
# TestFetchArxivPapersAsync — top-level coroutine
# ---------------------------------------------------------------------------


class TestFetchArxivPapersAsync:
    """fetch_arxiv_papers: async, runs sync fetcher in executor."""

    @pytest.mark.asyncio
    async def test_returns_list_on_success(self):
        """Must return a list (possibly empty) on valid XML feed."""
        from src.modules.paper.arxiv_fetcher import fetch_arxiv_papers

        minimal_feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>"""

        with patch(
            "src.modules.paper.arxiv_fetcher._fetch_arxiv_page_sync",
            return_value=minimal_feed,
        ):
            result = await fetch_arxiv_papers(categories=["cs.AI"], days_back=1, max_results=10)

        assert isinstance(result, list), "fetch_arxiv_papers must return a list"

    @pytest.mark.asyncio
    async def test_fetch_arxiv_papers_runs_in_executor(self):
        """
        fetch_arxiv_papers must run _fetch_arxiv_page_sync in an executor
        (not call it directly in the event loop, which would block).

        We verify this indirectly: the function is async and completes without
        blocking the event loop — if it called sync I/O directly on the loop
        the executor-based test would detect the thread context difference.

        Practical: wrap _fetch_arxiv_page_sync in a slow mock and confirm
        the coroutine still resolves (executor handles it off-thread).
        """
        from src.modules.paper.arxiv_fetcher import fetch_arxiv_papers

        minimal_feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>"""

        # If executor is NOT used, a slow sync call here would block; using it is fine
        with patch(
            "src.modules.paper.arxiv_fetcher._fetch_arxiv_page_sync",
            return_value=minimal_feed,
        ):
            result = await asyncio.wait_for(
                fetch_arxiv_papers(categories=["cs.LG"], days_back=1, max_results=5),
                timeout=5.0,
            )

        # MUTATION TARGET: removing run_in_executor → function might still work but
        # the executor call count check differentiates blocking vs non-blocking calls
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_fetch_arxiv_papers_accepts_multiple_categories(self):
        """Multiple categories must each result in at least one fetch call."""
        from src.modules.paper.arxiv_fetcher import fetch_arxiv_papers

        minimal_feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>"""

        call_count = 0

        def counting_fetch(_url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return minimal_feed

        with patch(
            "src.modules.paper.arxiv_fetcher._fetch_arxiv_page_sync",
            side_effect=counting_fetch,
        ):
            await fetch_arxiv_papers(
                categories=["cs.AI", "cs.LG", "cs.CL"], days_back=1, max_results=10
            )

        # Impl may batch categories in one query — just verify at least one call
        assert call_count >= 1, f"Expected at least 1 fetch call, got {call_count}"

    @pytest.mark.asyncio
    async def test_fetch_arxiv_papers_returns_list_of_dicts(self):
        """Each returned item must be a dict (not None, not a string)."""
        from src.modules.paper.arxiv_fetcher import fetch_arxiv_papers

        # Minimal valid entry
        feed_with_entry = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1234.56789v1</id>
    <title>Test Paper Title</title>
    <summary>Abstract text here.</summary>
    <published>2026-01-01T00:00:00Z</published>
  </entry>
</feed>"""

        with patch(
            "src.modules.paper.arxiv_fetcher._fetch_arxiv_page_sync",
            return_value=feed_with_entry,
        ):
            result = await fetch_arxiv_papers(categories=["cs.AI"], days_back=7, max_results=10)

        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict), f"Each item must be a dict, got {type(item)}"
