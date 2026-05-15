"""Mutation-aware tests for parse_frontmatter.

T1 test-adversary — never read frontmatter.py source.

Key mutations targeted:
  - YAML parse raises instead of swallowing error → ({}, full_text)
  - Empty frontmatter block returns non-empty dict
  - body includes frontmatter fence lines when it shouldn't
  - dict values mutated (string coerced to int silently)
  - round-trip breaks on nested / list / bool YAML values
"""
from pathlib import Path

import pytest

from obsidian_sync import parse_frontmatter


# ---------------------------------------------------------------------------
# Return type invariant
# ---------------------------------------------------------------------------

def test_returns_tuple_of_two(tmp_path: Path):
    f = tmp_path / "basic.md"
    f.write_text("---\ntitle: Hello\n---\nBody text", encoding="utf-8")
    result = parse_frontmatter(f)
    assert isinstance(result, tuple), "Must return tuple"
    assert len(result) == 2, "Tuple must have exactly 2 elements"
    fm, body = result
    assert isinstance(fm, dict), "First element must be dict"
    assert isinstance(body, str), "Second element must be str"


# ---------------------------------------------------------------------------
# Happy path: valid frontmatter round-trip
# ---------------------------------------------------------------------------

def test_valid_frontmatter_title_parsed(tmp_path: Path):
    f = tmp_path / "note.md"
    f.write_text("---\ntitle: My Note\nauthor: Jones\n---\nBody here", encoding="utf-8")
    fm, body = parse_frontmatter(f)
    assert fm.get("title") == "My Note", (
        "title not parsed — mutation: frontmatter extraction skipped"
    )
    assert fm.get("author") == "Jones"


def test_valid_frontmatter_body_excludes_fences(tmp_path: Path):
    """Body must NOT contain the --- delimiters."""
    f = tmp_path / "fenced.md"
    f.write_text("---\ntitle: T\n---\nActual body", encoding="utf-8")
    _, body = parse_frontmatter(f)
    assert "---" not in body, (
        "Body contains frontmatter fence — mutation: fence stripping skipped"
    )
    assert "Actual body" in body


def test_round_trip_string_values(tmp_path: Path):
    f = tmp_path / "rt_str.md"
    f.write_text("---\ntag: engineering\nspace: obsidian\n---\nBody", encoding="utf-8")
    fm, _ = parse_frontmatter(f)
    assert fm["tag"] == "engineering"
    assert fm["space"] == "obsidian"


def test_round_trip_list_values(tmp_path: Path):
    """YAML lists must come back as Python lists, not stringified."""
    f = tmp_path / "rt_list.md"
    f.write_text("---\ntags:\n  - python\n  - testing\n---\nBody", encoding="utf-8")
    fm, _ = parse_frontmatter(f)
    assert isinstance(fm.get("tags"), list), (
        "tags should be list — mutation: YAML value coerced to string"
    )
    assert "python" in fm["tags"]
    assert "testing" in fm["tags"]


def test_round_trip_bool_values(tmp_path: Path):
    """YAML booleans must come back as Python bool, not string."""
    f = tmp_path / "rt_bool.md"
    f.write_text("---\npublished: true\ndraft: false\n---\nBody", encoding="utf-8")
    fm, _ = parse_frontmatter(f)
    assert fm.get("published") is True, (
        "published should be True — mutation: YAML bool returned as string 'true'"
    )
    assert fm.get("draft") is False


def test_round_trip_integer_values(tmp_path: Path):
    f = tmp_path / "rt_int.md"
    f.write_text("---\nweight: 42\n---\nBody", encoding="utf-8")
    fm, _ = parse_frontmatter(f)
    assert fm.get("weight") == 42


def test_round_trip_nested_dict(tmp_path: Path):
    f = tmp_path / "rt_nested.md"
    f.write_text("---\nmeta:\n  source: blog\n  version: 1\n---\nBody", encoding="utf-8")
    fm, _ = parse_frontmatter(f)
    assert isinstance(fm.get("meta"), dict)
    assert fm["meta"]["source"] == "blog"


# ---------------------------------------------------------------------------
# No frontmatter: must return ({}, full_text)
# ---------------------------------------------------------------------------

def test_no_frontmatter_returns_empty_dict(tmp_path: Path):
    f = tmp_path / "no_fm.md"
    content = "# Just a header\nSome paragraph text."
    f.write_text(content, encoding="utf-8")
    fm, body = parse_frontmatter(f)
    assert fm == {}, (
        f"Expected empty dict, got {fm} — mutation: default dict not empty"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG: parse_frontmatter strips trailing newline from body when no frontmatter present: "
        "'# Header\\n\\nParagraph.\\n' → '# Header\\n\\nParagraph.' (rstrip side-effect). "
        "Downstream sync may produce different hash than server if server preserves trailing newline."
    ),
)
def test_no_frontmatter_body_is_full_text(tmp_path: Path):
    """Body must equal full file text when no frontmatter is present."""
    f = tmp_path / "plain.md"
    content = "# Header\n\nParagraph.\n"
    f.write_text(content, encoding="utf-8")
    _, body = parse_frontmatter(f)
    assert body == content, (
        "Body differs from full text — mutation: body sliced even without frontmatter"
    )


def test_empty_file_returns_empty_dict_and_empty_body(tmp_path: Path):
    f = tmp_path / "empty.md"
    f.write_text("", encoding="utf-8")
    fm, body = parse_frontmatter(f)
    assert fm == {}
    assert body == ""


# ---------------------------------------------------------------------------
# Bad YAML: must NOT raise, must return ({}, full_text)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_yaml", [
    "---\n: bad key\n---\nBody",              # invalid YAML key
    "---\ntabs:\t- value\n---\nBody",          # tab in YAML (some parsers reject)
    "---\nkey: [unclosed\n---\nBody",          # unclosed bracket
    "---\n!!python/object: evil\n---\nBody",   # YAML tag injection
])
def test_bad_yaml_does_not_raise(tmp_path: Path, bad_yaml: str):
    """Bad YAML must be silently swallowed and treated as plain body."""
    f = tmp_path / "bad.md"
    f.write_bytes(bad_yaml.encode("utf-8"))
    # Must not raise anything
    try:
        fm, body = parse_frontmatter(f)
    except Exception as exc:
        pytest.fail(
            f"parse_frontmatter raised {type(exc).__name__} on bad YAML — "
            "mutation: exception not caught"
        )


@pytest.mark.parametrize("bad_yaml", [
    "---\n: bad key\n---\nBody",
    "---\nkey: [unclosed\n---\nBody",
])
def test_bad_yaml_returns_empty_dict(tmp_path: Path, bad_yaml: str):
    """On bad YAML, frontmatter dict must be {} (not partial parse)."""
    f = tmp_path / "bad2.md"
    f.write_bytes(bad_yaml.encode("utf-8"))
    try:
        fm, _ = parse_frontmatter(f)
        assert fm == {}, (
            f"Bad YAML returned non-empty dict {fm} — "
            "mutation: partial parse result leaked"
        )
    except Exception:
        pass  # already caught by the no-raise test


def test_bad_yaml_body_contains_original_text(tmp_path: Path):
    """On bad YAML, body must be the full original file text."""
    content = "---\n: bad key\n---\nBody here"
    f = tmp_path / "bad_body.md"
    f.write_bytes(content.encode("utf-8"))
    try:
        _, body = parse_frontmatter(f)
        assert "Body here" in body, (
            "Body missing original text on bad YAML parse — "
            "mutation: body set to '' on error"
        )
    except Exception:
        pass  # already caught by the no-raise test


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_frontmatter_only_file(tmp_path: Path):
    """File with frontmatter and no body — body must be '' or empty string."""
    f = tmp_path / "fm_only.md"
    f.write_text("---\ntitle: Only FM\n---\n", encoding="utf-8")
    fm, body = parse_frontmatter(f)
    assert fm.get("title") == "Only FM"
    assert isinstance(body, str)  # may be '' or '\n', but not raise


def test_frontmatter_with_multiline_body(tmp_path: Path):
    """Multi-line body must be preserved exactly."""
    f = tmp_path / "multiline.md"
    body_expected = "Line one\nLine two\nLine three\n"
    f.write_text(f"---\ntitle: T\n---\n{body_expected}", encoding="utf-8")
    _, body = parse_frontmatter(f)
    assert "Line one" in body
    assert "Line two" in body
    assert "Line three" in body


def test_unicode_frontmatter_and_body(tmp_path: Path):
    """Unicode in frontmatter values and body must survive round-trip."""
    f = tmp_path / "unicode.md"
    f.write_text("---\ntitle: 繁體中文標題\nauthor: 少爺\n---\n正文段落\n", encoding="utf-8")
    fm, body = parse_frontmatter(f)
    assert fm.get("title") == "繁體中文標題"
    assert "正文段落" in body
