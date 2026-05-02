"""Tests for extract._http_post retry semantics.

Per contract:
- 2xx: immediate return, no retry
- 4xx: immediate return, no retry
- 5xx: retry up to 3 attempts with backoff 0.5s -> 1s
- Connection errors: retry up to 3 attempts, return (0, "") on exhaustion
"""

import io
import sys
import urllib.error
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/Users/joneshong/workshop/mcp/memvault/scripts")
from extract import _http_post


def _ok_response(status=200, body=b"ok"):
    """Build a context-manager mock for urlopen success."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _http_error(code, body):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))


@patch("time.sleep", return_value=None)
@patch("urllib.request.urlopen")
def test_2xx_no_retry(mock_urlopen, _sleep):
    mock_urlopen.return_value = _ok_response(200, b"ok")
    status, body = _http_post("http://x", {"a": 1})
    assert status == 200
    assert body == "ok"
    assert mock_urlopen.call_count == 1


@patch("time.sleep", return_value=None)
@patch("urllib.request.urlopen")
def test_4xx_no_retry(mock_urlopen, _sleep):
    mock_urlopen.side_effect = _http_error(400, b"bad")
    status, body = _http_post("http://x", {"a": 1})
    assert status == 400
    assert body == "bad"
    assert mock_urlopen.call_count == 1


@patch("time.sleep", return_value=None)
@patch("urllib.request.urlopen")
def test_5xx_retries_then_returns_last(mock_urlopen, _sleep):
    mock_urlopen.side_effect = [
        _http_error(503, b"busy"),
        _http_error(503, b"busy"),
        _http_error(503, b"busy"),
    ]
    status, body = _http_post("http://x", {"a": 1})
    assert status == 503
    assert body == "busy"
    assert mock_urlopen.call_count == 3


@patch("time.sleep", return_value=None)
@patch("urllib.request.urlopen")
def test_5xx_then_recovers(mock_urlopen, _sleep):
    mock_urlopen.side_effect = [
        _http_error(502, b""),
        _ok_response(200, b"ok"),
    ]
    status, body = _http_post("http://x", {"a": 1})
    assert status == 200
    assert body == "ok"
    assert mock_urlopen.call_count == 2


@patch("time.sleep", return_value=None)
@patch("urllib.request.urlopen")
def test_connection_error_retries(mock_urlopen, _sleep):
    mock_urlopen.side_effect = [
        urllib.error.URLError("dns"),
        urllib.error.URLError("dns"),
        urllib.error.URLError("dns"),
    ]
    status, body = _http_post("http://x", {"a": 1})
    assert status == 0
    assert body == ""
    assert mock_urlopen.call_count == 3


@patch("time.sleep", return_value=None)
@patch("urllib.request.urlopen")
def test_504_retries(mock_urlopen, _sleep):
    mock_urlopen.side_effect = [
        _http_error(504, b"gw timeout"),
        _http_error(504, b"gw timeout"),
        _http_error(504, b"gw timeout"),
    ]
    status, body = _http_post("http://x", {"a": 1})
    assert status == 504
    assert body == "gw timeout"
    assert mock_urlopen.call_count == 3
