"""
Test suite for ws_blog_gsc_index.py — test-adversary authored.

Invariants tested:
  INV-1: detect_changes() → empty when lastmods match state
  INV-2: detect_changes() → URL when lastmod newer than state
  INV-3: detect_changes() → URL when URL absent from state (new article)
  INV-4: detect_changes() → at most MAX_SUBMISSIONS URLs
  INV-5: update_state() only updates entries for URLs with status "ok"
  INV-6: Sitemap fetch failure → no crash, returns empty
  INV-7: XML namespace handling works correctly
  INV-8: state.json corruption → treated as empty, no crash

Additional:
  find_ref: real snapshot YAML content
  check_session_health: no false-positive on hidden reCAPTCHA
  SID truncation: verify SID truncated to 8 chars
  pw_close: must not throw even if subprocess fails
"""

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
import urllib.request
from io import BytesIO
from pathlib import Path
from unittest import mock

# Import the module under test
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ws_blog_gsc_index as mod

# ── Helpers ───────────────────────────────────────────────────────


def make_sitemap_xml(entries: dict[str, str]) -> bytes:
    """Build a valid sitemap XML from {url: lastmod} dict."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for loc, lastmod in entries.items():
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines).encode("utf-8")


def make_state(urls_dict: dict[str, dict]) -> dict:
    """Build a state.json-compatible dict."""
    return {"urls": urls_dict, "last_run": "2026-01-01T00:00:00"}


def mock_urlopen(xml_bytes: bytes):
    """Return a mock that replaces urllib.request.urlopen with in-memory bytes."""
    resp = BytesIO(xml_bytes)
    resp.status = 200
    cm = mock.MagicMock()
    cm.__enter__ = mock.Mock(return_value=resp)
    cm.__exit__ = mock.Mock(return_value=False)
    return mock.patch.object(urllib.request, "urlopen", return_value=cm)


# ── INV-1: No changes when lastmods match ────────────────────────


class TestINV1_NoChanges(unittest.TestCase):
    def test_all_urls_match(self):
        tmp_path = Path(tempfile.mkdtemp())
        """detect_changes returns empty when all lastmods match state."""
        entries = {
            "https://blog.joneshong.com/post-a/": "2026-03-20",
            "https://blog.joneshong.com/post-b/": "2026-03-19",
        }
        state = make_state(
            {
                "https://blog.joneshong.com/post-a/": {
                    "lastmod": "2026-03-20",
                    "last_submitted": "2026-03-20T10:00:00",
                    "status": "ok",
                },
                "https://blog.joneshong.com/post-b/": {
                    "lastmod": "2026-03-19",
                    "last_submitted": "2026-03-19T10:00:00",
                    "status": "ok",
                },
            }
        )
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))

        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            sitemap, changed = mod.detect_changes()

        assert changed == [], "Should return empty when all lastmods match"
        assert len(sitemap) == 2

    def test_mutation_eq_to_neq(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Mutation guard: if != mutated to ==, this must fail.

        We have matched lastmods but also inject one changed URL.
        If the comparison is correct, changed should contain the new one.
        """
        entries = {
            "https://blog.joneshong.com/post-a/": "2026-03-20",
            "https://blog.joneshong.com/post-b/": "2026-03-21",  # changed
        }
        state = make_state(
            {
                "https://blog.joneshong.com/post-a/": {
                    "lastmod": "2026-03-20",
                    "last_submitted": "2026-03-20T10:00:00",
                    "status": "ok",
                },
                "https://blog.joneshong.com/post-b/": {
                    "lastmod": "2026-03-19",
                    "last_submitted": "2026-03-19T10:00:00",
                    "status": "ok",
                },
            }
        )
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))

        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert "https://blog.joneshong.com/post-b/" in changed
        assert "https://blog.joneshong.com/post-a/" not in changed


# ── INV-2: Changed lastmod detected ──────────────────────────────


class TestINV2_ChangedLastmod(unittest.TestCase):
    def test_newer_lastmod_detected(self):
        tmp_path = Path(tempfile.mkdtemp())
        """URL should appear in changed when lastmod differs from state."""
        entries = {
            "https://blog.joneshong.com/post-a/": "2026-03-25",  # updated
        }
        state = make_state(
            {
                "https://blog.joneshong.com/post-a/": {
                    "lastmod": "2026-03-20",
                    "last_submitted": "2026-03-20T10:00:00",
                    "status": "ok",
                },
            }
        )
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))

        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert changed == ["https://blog.joneshong.com/post-a/"]

    def test_older_lastmod_also_detected(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Any difference in lastmod triggers change — not just newer.

        The code does != comparison, not > comparison. Verify this.
        """
        entries = {
            "https://blog.joneshong.com/post-a/": "2026-03-15",  # older than state
        }
        state = make_state(
            {
                "https://blog.joneshong.com/post-a/": {
                    "lastmod": "2026-03-20",
                    "last_submitted": "2026-03-20T10:00:00",
                    "status": "ok",
                },
            }
        )
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))

        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert "https://blog.joneshong.com/post-a/" in changed

    def test_empty_lastmod_vs_nonempty_state(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Empty lastmod in sitemap vs non-empty in state = change."""
        entries = {
            "https://blog.joneshong.com/post-a/": "",
        }
        state = make_state(
            {
                "https://blog.joneshong.com/post-a/": {
                    "lastmod": "2026-03-20",
                    "last_submitted": "2026-03-20T10:00:00",
                    "status": "ok",
                },
            }
        )
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))

        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert "https://blog.joneshong.com/post-a/" in changed


# ── INV-3: New URL (absent from state) ───────────────────────────


class TestINV3_NewURL(unittest.TestCase):
    def test_new_url_detected(self):
        tmp_path = Path(tempfile.mkdtemp())
        """URL not in state at all should be returned as changed."""
        entries = {
            "https://blog.joneshong.com/brand-new/": "2026-03-25",
        }
        state = make_state({})
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))

        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert changed == ["https://blog.joneshong.com/brand-new/"]

    def test_missing_state_file(self):
        tmp_path = Path(tempfile.mkdtemp())
        """If state.json doesn't exist, all URLs should be changed."""
        entries = {
            "https://blog.joneshong.com/post-a/": "2026-03-20",
            "https://blog.joneshong.com/post-b/": "2026-03-19",
        }
        state_file = tmp_path / "state.json"  # does not exist

        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert len(changed) == 2
        assert set(changed) == {
            "https://blog.joneshong.com/post-a/",
            "https://blog.joneshong.com/post-b/",
        }


# ── INV-4: MAX_SUBMISSIONS cap ───────────────────────────────────


class TestINV4_MaxSubmissions(unittest.TestCase):
    def test_cap_at_max_submissions(self):
        tmp_path = Path(tempfile.mkdtemp())
        """detect_changes never returns more than MAX_SUBMISSIONS URLs."""
        num = mod.MAX_SUBMISSIONS + 5
        entries = {
            f"https://blog.joneshong.com/post-{i}/": f"2026-03-{20 + i % 10:02d}"
            for i in range(num)
        }
        state = make_state({})
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))

        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert len(changed) == mod.MAX_SUBMISSIONS

    def test_exact_max_submissions(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Exactly MAX_SUBMISSIONS changes should all be returned."""
        entries = {
            f"https://blog.joneshong.com/post-{i}/": "2026-03-25"
            for i in range(mod.MAX_SUBMISSIONS)
        }
        state = make_state({})
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))

        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert len(changed) == mod.MAX_SUBMISSIONS

    def test_max_submissions_is_positive(self):
        """Sanity: MAX_SUBMISSIONS must be a positive integer."""
        assert isinstance(mod.MAX_SUBMISSIONS, int)
        assert mod.MAX_SUBMISSIONS > 0


# ── INV-5: update_state only persists "ok" URLs ──────────────────


class TestINV5_UpdateState(unittest.TestCase):
    def test_only_ok_urls_updated(self):
        tmp_path = Path(tempfile.mkdtemp())
        """URLs with non-ok status must not be persisted to state."""
        sitemap = {
            "https://blog.joneshong.com/post-a/": "2026-03-25",
            "https://blog.joneshong.com/post-b/": "2026-03-25",
            "https://blog.joneshong.com/post-c/": "2026-03-25",
        }
        results = {
            "https://blog.joneshong.com/post-a/": "ok",
            "https://blog.joneshong.com/post-b/": "timeout",
            "https://blog.joneshong.com/post-c/": "CAPTCHA detected",
        }

        state_file = tmp_path / "state.json"
        state_dir = tmp_path
        state_file.write_text(json.dumps({"urls": {}}))

        with (
            mock.patch.object(mod, "STATE_FILE", state_file),
            mock.patch.object(mod, "STATE_DIR", state_dir),
        ):
            mod.update_state(sitemap, results)

        saved = json.loads(state_file.read_text())
        assert "https://blog.joneshong.com/post-a/" in saved["urls"]
        assert "https://blog.joneshong.com/post-b/" not in saved["urls"]
        assert "https://blog.joneshong.com/post-c/" not in saved["urls"]

    def test_ok_url_gets_correct_lastmod(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Persisted entry's lastmod must match the sitemap value."""
        sitemap = {
            "https://blog.joneshong.com/post-a/": "2026-03-25",
        }
        results = {
            "https://blog.joneshong.com/post-a/": "ok",
        }

        state_file = tmp_path / "state.json"
        state_dir = tmp_path
        state_file.write_text(json.dumps({"urls": {}}))

        with (
            mock.patch.object(mod, "STATE_FILE", state_file),
            mock.patch.object(mod, "STATE_DIR", state_dir),
        ):
            mod.update_state(sitemap, results)

        saved = json.loads(state_file.read_text())
        entry = saved["urls"]["https://blog.joneshong.com/post-a/"]
        assert entry["lastmod"] == "2026-03-25"
        assert entry["status"] == "ok"
        assert "last_submitted" in entry

    def test_failed_url_preserves_old_state(self):
        tmp_path = Path(tempfile.mkdtemp())
        """A failed URL should leave existing state entry untouched."""
        old_entry = {
            "lastmod": "2026-03-20",
            "last_submitted": "2026-03-20T10:00:00",
            "status": "ok",
        }
        state_file = tmp_path / "state.json"
        state_dir = tmp_path
        state_file.write_text(
            json.dumps({"urls": {"https://blog.joneshong.com/post-a/": old_entry}})
        )

        sitemap = {"https://blog.joneshong.com/post-a/": "2026-03-25"}
        results = {"https://blog.joneshong.com/post-a/": "button_not_found"}

        with (
            mock.patch.object(mod, "STATE_FILE", state_file),
            mock.patch.object(mod, "STATE_DIR", state_dir),
        ):
            mod.update_state(sitemap, results)

        saved = json.loads(state_file.read_text())
        entry = saved["urls"]["https://blog.joneshong.com/post-a/"]
        # Old entry preserved because "button_not_found" != "ok"
        assert entry["lastmod"] == "2026-03-20"
        assert entry["status"] == "ok"

    def test_last_run_always_updated(self):
        tmp_path = Path(tempfile.mkdtemp())
        """state.last_run should be updated even when all URLs fail."""
        state_file = tmp_path / "state.json"
        state_dir = tmp_path
        state_file.write_text(json.dumps({"urls": {}}))

        sitemap = {"https://blog.joneshong.com/post-a/": "2026-03-25"}
        results = {"https://blog.joneshong.com/post-a/": "timeout"}

        with (
            mock.patch.object(mod, "STATE_FILE", state_file),
            mock.patch.object(mod, "STATE_DIR", state_dir),
        ):
            mod.update_state(sitemap, results)

        saved = json.loads(state_file.read_text())
        assert "last_run" in saved

    def test_mutation_ok_literal(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Mutation guard: if 'ok' string changes to 'OK' or 'Ok', test must catch."""
        sitemap = {"https://blog.joneshong.com/post-a/": "2026-03-25"}
        # "OK" (uppercase) should NOT be treated as success
        results = {"https://blog.joneshong.com/post-a/": "OK"}

        state_file = tmp_path / "state.json"
        state_dir = tmp_path
        state_file.write_text(json.dumps({"urls": {}}))

        with (
            mock.patch.object(mod, "STATE_FILE", state_file),
            mock.patch.object(mod, "STATE_DIR", state_dir),
        ):
            mod.update_state(sitemap, results)

        saved = json.loads(state_file.read_text())
        # "OK" != "ok" so it must NOT be persisted
        assert "https://blog.joneshong.com/post-a/" not in saved["urls"]


# ── INV-6: Sitemap fetch failure ──────────────────────────────────


class TestINV6_SitemapFetchFailure(unittest.TestCase):
    def test_network_error(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Network error during fetch → empty dict, no crash."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"urls": {}}))

        with (
            mock.patch.object(
                urllib.request,
                "urlopen",
                side_effect=urllib.error.URLError("Connection refused"),
            ),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            sitemap, changed = mod.detect_changes()

        assert sitemap == {}
        assert changed == []

    def test_timeout_error(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Timeout during fetch → empty dict, no crash."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"urls": {}}))

        with (
            mock.patch.object(
                urllib.request,
                "urlopen",
                side_effect=TimeoutError("timed out"),
            ),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            sitemap, changed = mod.detect_changes()

        assert sitemap == {}
        assert changed == []

    def test_invalid_xml(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Malformed XML → empty dict, no crash."""
        bad_xml = b"<not valid xml!!!>"
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"urls": {}}))

        with (
            mock_urlopen(bad_xml),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            sitemap, changed = mod.detect_changes()

        assert sitemap == {}
        assert changed == []

    def test_empty_xml(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Empty XML body → empty dict, no crash."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"urls": {}}))

        with (
            mock_urlopen(b""),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            sitemap, changed = mod.detect_changes()

        assert sitemap == {}
        assert changed == []


# ── INV-7: XML namespace handling ─────────────────────────────────


class TestINV7_XMLNamespace(unittest.TestCase):
    def test_standard_namespace(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Standard sitemap namespace must be parsed correctly."""
        xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url>
                <loc>https://blog.joneshong.com/post-1/</loc>
                <lastmod>2026-03-25</lastmod>
              </url>
            </urlset>
        """).encode()

        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"urls": {}}))

        with (
            mock_urlopen(xml),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            sitemap, changed = mod.detect_changes()

        assert "https://blog.joneshong.com/post-1/" in sitemap
        assert sitemap["https://blog.joneshong.com/post-1/"] == "2026-03-25"

    def test_namespace_constant_matches(self):
        """Verify the hardcoded namespace matches sitemap.org spec."""
        assert mod.SITEMAP_NS == "{http://www.sitemaps.org/schemas/sitemap/0.9}"

    def test_url_without_lastmod(self):
        tmp_path = Path(tempfile.mkdtemp())
        """URL element with no lastmod should have empty string."""
        xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url>
                <loc>https://blog.joneshong.com/no-lastmod/</loc>
              </url>
            </urlset>
        """).encode()

        with mock_urlopen(xml):
            result = mod.fetch_sitemap()

        assert "https://blog.joneshong.com/no-lastmod/" in result
        assert result["https://blog.joneshong.com/no-lastmod/"] == ""

    def test_wrong_namespace_yields_empty(self):
        """If namespace is different, findall won't match → empty dict."""
        xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <urlset xmlns="http://www.example.com/wrong-ns">
              <url>
                <loc>https://blog.joneshong.com/post-1/</loc>
                <lastmod>2026-03-25</lastmod>
              </url>
            </urlset>
        """).encode()

        with mock_urlopen(xml):
            result = mod.fetch_sitemap()

        assert result == {}


# ── INV-8: Corrupt state.json ─────────────────────────────────────


class TestINV8_CorruptState(unittest.TestCase):
    def test_corrupt_json(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Corrupt JSON → load_state returns empty dict, no crash."""
        state_file = tmp_path / "state.json"
        state_file.write_text("{broken json!!!")

        with mock.patch.object(mod, "STATE_FILE", state_file):
            result = mod.load_state()

        assert result == {}

    def test_empty_file(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Empty file → load_state returns empty dict."""
        state_file = tmp_path / "state.json"
        state_file.write_text("")

        with mock.patch.object(mod, "STATE_FILE", state_file):
            result = mod.load_state()

        assert result == {}

    def test_corrupt_state_in_detect_changes(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Corrupt state.json should not crash detect_changes — all URLs changed."""
        entries = {
            "https://blog.joneshong.com/post-a/": "2026-03-25",
        }
        state_file = tmp_path / "state.json"
        state_file.write_text("not json at all")

        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert changed == ["https://blog.joneshong.com/post-a/"]

    def test_valid_json_but_no_urls_key(self):
        tmp_path = Path(tempfile.mkdtemp())
        """Valid JSON with missing 'urls' key → treat as empty state."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"some_other_key": "value"}))

        entries = {
            "https://blog.joneshong.com/post-a/": "2026-03-25",
        }

        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert "https://blog.joneshong.com/post-a/" in changed

    def test_binary_garbage_crashes(self):
        tmp_path = Path(tempfile.mkdtemp())
        """BUG FOUND: Binary data in state.json raises UnicodeDecodeError.

        load_state() catches (json.JSONDecodeError, OSError) but
        STATE_FILE.read_text() raises UnicodeDecodeError (a ValueError)
        when the file contains non-UTF-8 bytes. This is NOT caught.

        FIX: Add ValueError (or UnicodeDecodeError) to the except clause
        in load_state(), line 102:
            except (json.JSONDecodeError, OSError, ValueError):
        """
        state_file = tmp_path / "state.json"
        state_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe")

        with mock.patch.object(mod, "STATE_FILE", state_file):
            # After fix: ValueError (UnicodeDecodeError) is caught, returns {}
            result = mod.load_state()
            self.assertEqual(result, {})


# ── find_ref: real snapshot YAML content ──────────────────────────


class TestFindRef(unittest.TestCase):
    # Realistic Playwright accessibility tree snapshot
    SNAPSHOT = textwrap.dedent("""\
        - navigation "Main navigation":
          - link "Search Console" [ref=e1]
        - main:
          - combobox "檢查任何網址" [ref=e5]
          - button "執行" [ref=e6]
          - heading "網址檢查" [ref=e7]
          - button "要求建立索引" [ref=e10]
          - button "關閉" [ref=e11]
          - paragraph:
            - text "已要求建立索引"
    """)

    SNAPSHOT_EN = textwrap.dedent("""\
        - navigation "Main":
          - link "Search Console" [ref=e1]
        - main:
          - combobox "Inspect any URL in" [ref=e5]
          - button "Run" [ref=e6]
          - button "Request Indexing" [ref=e10]
          - button "Close" [ref=e11]
    """)

    def test_find_combobox_zh(self):
        """Find Chinese combobox ref."""
        ref = mod.find_ref(self.SNAPSHOT, r"combobox.*檢查")
        assert ref == "e5"

    def test_find_button_zh(self):
        """Find request indexing button (Chinese)."""
        ref = mod.find_ref(self.SNAPSHOT, r"要求建立索引")
        assert ref == "e10"

    def test_find_close_button_zh(self):
        """Find close button (Chinese)."""
        ref = mod.find_ref(self.SNAPSHOT, r"button.*關閉")
        assert ref == "e11"

    def test_find_combobox_en(self):
        """Find English combobox ref."""
        ref = mod.find_ref(self.SNAPSHOT_EN, r"combobox.*Inspect")
        assert ref == "e5"

    def test_find_button_en(self):
        """Find request indexing button (English)."""
        ref = mod.find_ref(self.SNAPSHOT_EN, r"Request [Ii]ndexing")
        assert ref == "e10"

    def test_not_found_returns_none(self):
        """Non-existent pattern returns None."""
        ref = mod.find_ref(self.SNAPSHOT, r"nonexistent_element")
        assert ref is None

    def test_case_insensitive(self):
        """Pattern matching is case-insensitive."""
        ref = mod.find_ref(self.SNAPSHOT_EN, r"request indexing")
        assert ref == "e10"

    def test_empty_snapshot(self):
        """Empty snapshot returns None."""
        ref = mod.find_ref("", r"anything")
        assert ref is None

    def test_ref_format(self):
        """Returned ref must match e-digit pattern."""
        ref = mod.find_ref(self.SNAPSHOT, r"combobox.*檢查")
        assert ref is not None
        import re

        assert re.match(r"^e\d+$", ref)


# ── check_session_health ──────────────────────────────────────────


class TestCheckSessionHealth(unittest.TestCase):
    def test_healthy_gsc_page(self):
        """Normal GSC page → None (healthy)."""
        snap = textwrap.dedent("""\
            - heading "Search Console"
            - combobox "檢查任何網址" [ref=e5]
            - button "執行" [ref=e6]
        """)
        assert mod.check_session_health(snap) is None

    def test_captcha_detected(self):
        """Visible CAPTCHA challenge → error string."""
        snap = "Please verify you are not a robot\nI'm not a robot"
        result = mod.check_session_health(snap)
        assert result == "CAPTCHA detected"

    def test_hidden_recaptcha_no_false_positive(self):
        """Hidden reCAPTCHA v3 script references must NOT trigger false positive.

        Google pages commonly embed invisible reCAPTCHA. The script tag or
        iframe with 'recaptcha' should not be confused with a visible CAPTCHA.
        """
        snap = textwrap.dedent("""\
            - heading "Search Console"
            - combobox "檢查任何網址" [ref=e5]
            - iframe "recaptcha challenge"
            - script src="https://www.google.com/recaptcha/api.js?render=..."
        """)
        # This should NOT be a CAPTCHA detection — it's a reference to
        # recaptcha script but NOT the "I'm not a robot" challenge
        assert mod.check_session_health(snap) is None

    def test_login_page_detected(self):
        """Google login page without GSC context → Login required."""
        snap = textwrap.dedent("""\
            - heading "Sign in"
            - text "Google Account"
            - textbox "Email"
        """)
        result = mod.check_session_health(snap)
        assert result == "Login required"

    def test_login_zh_detected(self):
        """Chinese login page detection."""
        snap = textwrap.dedent("""\
            - heading "登入"
            - text "Google 帳戶"
            - textbox "電子郵件"
        """)
        result = mod.check_session_health(snap)
        assert result == "Login required"

    def test_gsc_page_with_sign_in_link_no_false_positive(self):
        """GSC page that contains 'Sign in' text in nav should NOT trigger."""
        snap = textwrap.dedent("""\
            - heading "Search Console"
            - link "Sign in with another account"
            - combobox "Inspect any URL" [ref=e5]
        """)
        # "Search Console" is present → not treated as login page
        assert mod.check_session_health(snap) is None

    def test_search_console_in_url_context(self):
        """Page with 'search-console' in content is not a login page."""
        snap = textwrap.dedent("""\
            - link "search-console/performance"
            - text "Sign in to view your data"
            - text "google"
        """)
        # "search-console" is present → not treated as login page
        assert mod.check_session_health(snap) is None


# ── SID truncation ────────────────────────────────────────────────


class TestSIDTruncation(unittest.TestCase):
    def test_long_sid_truncated(self):
        """SID longer than 8 chars should be truncated."""
        stdout = "export PW_PROFILE=/tmp/pw-abc123def\nexport SID=abcdefghijklmnop\n"
        mock_result = mock.MagicMock()
        mock_result.stdout = stdout
        mock_result.returncode = 0

        with mock.patch.object(subprocess, "run", return_value=mock_result):
            profile, sid = mod.pw_init()

        assert sid == "abcdefgh"
        assert len(sid) == 8

    def test_short_sid_unchanged(self):
        """SID of exactly 8 chars should not be modified."""
        stdout = "export PW_PROFILE=/tmp/pw-short\nexport SID=12345678\n"
        mock_result = mock.MagicMock()
        mock_result.stdout = stdout
        mock_result.returncode = 0

        with mock.patch.object(subprocess, "run", return_value=mock_result):
            profile, sid = mod.pw_init()

        assert sid == "12345678"

    def test_very_short_sid_unchanged(self):
        """SID shorter than 8 chars should not be modified."""
        stdout = "export PW_PROFILE=/tmp/pw-tiny\nexport SID=abc\n"
        mock_result = mock.MagicMock()
        mock_result.stdout = stdout
        mock_result.returncode = 0

        with mock.patch.object(subprocess, "run", return_value=mock_result):
            profile, sid = mod.pw_init()

        assert sid == "abc"

    def test_no_sid_returns_none(self):
        """If SID line is missing, sid should be None."""
        stdout = "export PW_PROFILE=/tmp/pw-nosid\n"
        mock_result = mock.MagicMock()
        mock_result.stdout = stdout
        mock_result.returncode = 0

        with mock.patch.object(subprocess, "run", return_value=mock_result):
            profile, sid = mod.pw_init()

        assert profile == "/tmp/pw-nosid"
        assert sid is None

    def test_profile_parsed_correctly(self):
        """Profile dir should be parsed from stdout."""
        stdout = "export PW_PROFILE=/tmp/pw-abc123def\nexport SID=abcdef12\n"
        mock_result = mock.MagicMock()
        mock_result.stdout = stdout
        mock_result.returncode = 0

        with mock.patch.object(subprocess, "run", return_value=mock_result):
            profile, sid = mod.pw_init()

        assert profile == "/tmp/pw-abc123def"

    def test_quoted_values_stripped(self):
        """Quotes around values should be stripped."""
        stdout = "export PW_PROFILE='/tmp/pw-quoted'\nexport SID=\"abcdefghijkl\"\n"
        mock_result = mock.MagicMock()
        mock_result.stdout = stdout
        mock_result.returncode = 0

        with mock.patch.object(subprocess, "run", return_value=mock_result):
            profile, sid = mod.pw_init()

        assert profile == "/tmp/pw-quoted"
        assert sid == "abcdefgh"


# ── pw_close resilience ───────────────────────────────────────────


class TestPwClose(unittest.TestCase):
    def test_no_throw_on_subprocess_failure(self):
        """pw_close must not throw even if subprocess fails."""
        with mock.patch.object(
            subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(1, "playwright-cli"),
        ):
            # Should not raise
            mod.pw_close("test-sid", "/tmp/pw-test")

    def test_no_throw_on_timeout(self):
        """pw_close must not throw on timeout."""
        with mock.patch.object(
            subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("playwright-cli", 10),
        ):
            mod.pw_close("test-sid", "/tmp/pw-test")

    def test_no_throw_on_file_not_found(self):
        """pw_close must not throw if playwright-cli is not found."""
        with mock.patch.object(
            subprocess,
            "run",
            side_effect=FileNotFoundError("playwright-cli not found"),
        ):
            mod.pw_close("test-sid", "/tmp/pw-test")

    def test_no_throw_on_os_error(self):
        """pw_close must not throw on generic OS errors."""
        with mock.patch.object(
            subprocess,
            "run",
            side_effect=OSError("generic OS error"),
        ):
            mod.pw_close("test-sid", "/tmp/pw-test")


# ── Integration: detect_changes + update_state roundtrip ──────────


class TestRoundtrip(unittest.TestCase):
    def test_submit_then_no_change(self):
        tmp_path = Path(tempfile.mkdtemp())
        """After successful update_state, same sitemap should show no changes."""
        entries = {
            "https://blog.joneshong.com/post-a/": "2026-03-25",
        }
        sitemap = entries.copy()
        results = {"https://blog.joneshong.com/post-a/": "ok"}

        state_file = tmp_path / "state.json"
        state_dir = tmp_path
        state_file.write_text(json.dumps({"urls": {}}))

        # First: update state with ok result
        with (
            mock.patch.object(mod, "STATE_FILE", state_file),
            mock.patch.object(mod, "STATE_DIR", state_dir),
        ):
            mod.update_state(sitemap, results)

        # Second: detect changes with same sitemap
        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert changed == [], "No changes after successful submission"

    def test_failed_submit_then_retry_detected(self):
        tmp_path = Path(tempfile.mkdtemp())
        """After failed update_state, same sitemap should still show changes."""
        entries = {
            "https://blog.joneshong.com/post-a/": "2026-03-25",
        }
        sitemap = entries.copy()
        results = {"https://blog.joneshong.com/post-a/": "timeout"}

        state_file = tmp_path / "state.json"
        state_dir = tmp_path
        state_file.write_text(json.dumps({"urls": {}}))

        # First: update state with failure
        with (
            mock.patch.object(mod, "STATE_FILE", state_file),
            mock.patch.object(mod, "STATE_DIR", state_dir),
        ):
            mod.update_state(sitemap, results)

        # Second: detect changes — should still be changed
        with (
            mock_urlopen(make_sitemap_xml(entries)),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            _, changed = mod.detect_changes()

        assert changed == ["https://blog.joneshong.com/post-a/"]


# ── Edge cases & regression ───────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    def test_sitemap_url_is_localhost_not_public(self):
        """Regression: SITEMAP_URL must fetch from localhost, not public blog.

        The sitemap is fetched from the local blog server.
        """
        assert "127.0.0.1" in mod.SITEMAP_URL or "localhost" in mod.SITEMAP_URL

    def test_gsc_property_is_public_domain(self):
        """The GSC property must be the public blog URL, not localhost."""
        assert "localhost" not in mod.GSC_PROPERTY
        assert "127.0.0.1" not in mod.GSC_PROPERTY
        assert "blog.joneshong.com" in mod.GSC_PROPERTY

    def test_sitemap_url_targets_posts(self):
        """Must fetch sitemap-posts.xml specifically."""
        assert "sitemap-posts.xml" in mod.SITEMAP_URL

    def test_detect_changes_returns_tuple(self):
        tmp_path = Path(tempfile.mkdtemp())
        """detect_changes must return (dict, list) tuple."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"urls": {}}))

        with (
            mock.patch.object(
                urllib.request,
                "urlopen",
                side_effect=Exception("fail"),
            ),
            mock.patch.object(mod, "STATE_FILE", state_file),
        ):
            result = mod.detect_changes()

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], dict)
        assert isinstance(result[1], list)

    def test_fetch_sitemap_empty_urlset(self):
        """Sitemap with no <url> entries → empty dict."""
        xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            </urlset>
        """).encode()

        with mock_urlopen(xml):
            result = mod.fetch_sitemap()

        assert result == {}

    def test_fetch_sitemap_loc_empty(self):
        """URL entry with empty <loc> should be skipped."""
        xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url>
                <loc></loc>
                <lastmod>2026-03-25</lastmod>
              </url>
              <url>
                <loc>https://blog.joneshong.com/real/</loc>
                <lastmod>2026-03-25</lastmod>
              </url>
            </urlset>
        """).encode()

        with mock_urlopen(xml):
            result = mod.fetch_sitemap()

        # Empty loc should be excluded
        assert "" not in result
        assert "https://blog.joneshong.com/real/" in result

    def test_state_json_urls_is_dict_not_list(self):
        tmp_path = Path(tempfile.mkdtemp())
        """state.json.urls must be a dict keyed by URL, not a list."""
        state_file = tmp_path / "state.json"
        state_dir = tmp_path
        state_file.write_text(json.dumps({"urls": {}}))

        sitemap = {"https://blog.joneshong.com/post-a/": "2026-03-25"}
        results = {"https://blog.joneshong.com/post-a/": "ok"}

        with (
            mock.patch.object(mod, "STATE_FILE", state_file),
            mock.patch.object(mod, "STATE_DIR", state_dir),
        ):
            mod.update_state(sitemap, results)

        saved = json.loads(state_file.read_text())
        assert isinstance(saved["urls"], dict)
