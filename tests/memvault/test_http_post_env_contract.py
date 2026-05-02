"""Tests for extract._http_post env-implicit auth contract.

Contract:
- Reads CORE_INTERNAL_API_KEY from os.environ
- Non-empty string -> inject header X-Internal-Key: <key>
- Empty string or unset -> do NOT inject X-Internal-Key (silent, no raise, no log)
- No explicit auth parameter accepted

These tests lock the contract so any future drift (e.g. raising on unset, or
falling back to a default key) is caught immediately.

NOTE: Real CORE_INTERNAL_API_KEY value must NEVER be printed in test output.
"""

import io
import os
import sys
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "/Users/joneshong/workshop/mcp/memvault/scripts")
from extract import _http_post


def _ok_response(status=200, body=b"ok"):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _http_error(code, body):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))


def _captured_request(mock_urlopen):
    """Pull the urllib.request.Request object from the first urlopen call."""
    assert mock_urlopen.call_count >= 1, "urlopen was not called"
    args, kwargs = mock_urlopen.call_args_list[0]
    req = args[0] if args else kwargs.get("url") or kwargs.get("req")
    assert req is not None, "could not extract Request object from urlopen call"
    return req


# ---------------------------------------------------------------------------
# 1. env set -> header injected
# ---------------------------------------------------------------------------
@patch("time.sleep", return_value=None)
@patch("urllib.request.urlopen")
def test_env_set_injects_header(mock_urlopen, _sleep, monkeypatch):
    monkeypatch.setenv("CORE_INTERNAL_API_KEY", "fake_key_123")
    mock_urlopen.return_value = _ok_response(200, b"ok")

    status, _ = _http_post("http://x", {"a": 1})
    assert status == 200

    req = _captured_request(mock_urlopen)
    # urllib lowercases header names internally via get_header capitalisation
    header_val = req.get_header("X-internal-key")
    assert header_val == "fake_key_123", (
        "expected X-Internal-Key header to be injected when env is set"
    )


# ---------------------------------------------------------------------------
# 2. env unset -> header omitted
# ---------------------------------------------------------------------------
@patch("time.sleep", return_value=None)
@patch("urllib.request.urlopen")
def test_env_unset_omits_header(mock_urlopen, _sleep, monkeypatch):
    monkeypatch.delenv("CORE_INTERNAL_API_KEY", raising=False)
    mock_urlopen.return_value = _ok_response(200, b"ok")

    status, _ = _http_post("http://x", {"a": 1})
    assert status == 200

    req = _captured_request(mock_urlopen)
    header_val = req.get_header("X-internal-key")
    assert header_val is None, (
        "X-Internal-Key must NOT be injected when CORE_INTERNAL_API_KEY is unset"
    )


# ---------------------------------------------------------------------------
# 3. env empty string -> header omitted (empty == unset)
# ---------------------------------------------------------------------------
@patch("time.sleep", return_value=None)
@patch("urllib.request.urlopen")
def test_env_empty_string_omits_header(mock_urlopen, _sleep, monkeypatch):
    monkeypatch.setenv("CORE_INTERNAL_API_KEY", "")
    mock_urlopen.return_value = _ok_response(200, b"ok")

    status, _ = _http_post("http://x", {"a": 1})
    assert status == 200

    req = _captured_request(mock_urlopen)
    header_val = req.get_header("X-internal-key")
    assert header_val is None, (
        "X-Internal-Key must NOT be injected when CORE_INTERNAL_API_KEY is empty string"
    )


# ---------------------------------------------------------------------------
# 4. env unset -> _http_post does not raise (returns the 401 silently)
# ---------------------------------------------------------------------------
@patch("time.sleep", return_value=None)
@patch("urllib.request.urlopen")
def test_env_unset_no_exception(mock_urlopen, _sleep, monkeypatch):
    monkeypatch.delenv("CORE_INTERNAL_API_KEY", raising=False)
    mock_urlopen.side_effect = _http_error(401, b"unauthorized")

    # Must NOT raise — must return tuple
    status, body = _http_post("http://x", {"a": 1})
    assert status == 401
    assert body == "unauthorized"


# ---------------------------------------------------------------------------
# 5. integration: real Core returns 401/403 when env is missing
# ---------------------------------------------------------------------------
def test_real_core_401_without_env(monkeypatch):
    url = "http://localhost:10000/api/memvault/dream?space_id=default&dry_run=true&force=true"

    # 1) Confirm Core is reachable; if not, skip (do NOT fail).
    import socket

    try:
        s = socket.create_connection(("localhost", 10000), timeout=2)
        s.close()
    except OSError:
        pytest.skip("Core API not reachable on localhost:10000")

    # 2) Strip env for the duration of this test only. monkeypatch auto-restores.
    monkeypatch.delenv("CORE_INTERNAL_API_KEY", raising=False)
    # Defensive: also ensure os.environ truly does not contain it
    assert os.environ.get("CORE_INTERNAL_API_KEY", "") == ""

    status, _body = _http_post(url, {}, timeout=30)

    # Accept 401 or 403 — both prove auth is enforced and key was not injected.
    # Do NOT assert on body content (avoid leaking server-side details).
    assert status in (401, 403), (
        f"expected Core to reject unauthenticated request with 401/403, got {status}"
    )
