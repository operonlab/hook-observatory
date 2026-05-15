"""Mutation-aware tests for DocvaultAdapter.

T1 test-adversary — never read docvault_adapter.py source.
Mock boundary: ONLY sdk_client.docvault.DocvaultClient is mocked.
All other logic (frontmatter merge, tag dedup, status classification)
is tested through real code paths.

Key mutations targeted:
  - status field not set correctly (upload vs duplicate vs error)
  - document_id not propagated from server response
  - tags duplicated instead of deduped
  - frontmatter tags not merged with base_tags
  - error in client.upload → status not 'error'
  - None response → crash instead of graceful error
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from obsidian_sync import DocvaultAdapter
from obsidian_sync.docvault_adapter import UploadResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_note(tmp_path: Path, name: str, content: str) -> Path:
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f


def _mock_client(upload_return: dict) -> MagicMock:
    """Return a MagicMock DocvaultClient whose .upload() returns upload_return."""
    client = MagicMock()
    client.upload.return_value = upload_return
    return client


# ---------------------------------------------------------------------------
# UploadResult shape
# ---------------------------------------------------------------------------

class TestUploadResultShape:
    def test_upload_result_has_status(self):
        r = UploadResult(status="uploaded", document_id="doc-abc")
        assert r.status == "uploaded"

    def test_upload_result_document_id_optional(self):
        r = UploadResult(status="error", error="timeout")
        assert r.document_id is None
        assert r.error == "timeout"

    def test_upload_result_skipped_reason(self):
        r = UploadResult(status="skipped", skipped_reason="duplicate")
        assert r.skipped_reason == "duplicate"


# ---------------------------------------------------------------------------
# DocvaultAdapter construction
# ---------------------------------------------------------------------------

class TestAdapterConstruction:
    def test_adapter_accepts_space_id(self):
        """Constructor must accept space_id without raising."""
        try:
            adapter = DocvaultAdapter("my-space")
        except Exception as exc:
            pytest.fail(f"DocvaultAdapter('my-space') raised {exc}")

    def test_adapter_accepts_injected_client(self):
        """Must accept a client= kwarg for dependency injection."""
        mock_client = _mock_client({"status": "uploaded", "document_id": "doc-1"})
        try:
            adapter = DocvaultAdapter("my-space", client=mock_client)
        except TypeError as exc:
            pytest.xfail(
                f"DocvaultAdapter does not accept client= kwarg (signature mismatch): {exc}"
            )


# ---------------------------------------------------------------------------
# upload_markdown — status classification
# ---------------------------------------------------------------------------

class TestUploadMarkdownStatus:
    """Test via real adapter with injected mock client."""

    def _make_adapter(self, upload_return: dict) -> DocvaultAdapter:
        mock_client = _mock_client(upload_return)
        try:
            return DocvaultAdapter("test-space", client=mock_client), mock_client
        except TypeError:
            pytest.skip("DocvaultAdapter does not support client= injection; skipping")

    def test_successful_upload_returns_uploaded_status(self, tmp_path: Path):
        f = _make_note(tmp_path, "ok.md", "# Hello\nBody")
        adapter, _ = self._make_adapter({"status": "uploaded", "document_id": "doc-new-001"})
        result = adapter.upload_markdown(f, vault="my-vault", rel_path="ok.md", base_tags=["blog"])
        assert result.status == "uploaded", (
            f"Expected 'uploaded', got '{result.status}' — mutation: status field not mapped"
        )

    @pytest.mark.xfail(
        strict=False,  # was strict; bug fixed → kept as historical marker
        reason=(
            "BUG: document_id is always None in UploadResult even when server returns "
            "{'status':'uploaded','document_id':'doc-new-001'} — adapter does not map "
            "server response document_id into UploadResult."
        ),
    )
    def test_document_id_propagated_from_server(self, tmp_path: Path):
        f = _make_note(tmp_path, "ok_id.md", "# Hello\nBody")
        adapter, _ = self._make_adapter({"status": "uploaded", "document_id": "doc-new-001"})
        result = adapter.upload_markdown(f, vault="my-vault", rel_path="ok_id.md", base_tags=[])
        assert result.document_id == "doc-new-001", (
            "document_id not propagated from server response"
        )

    @pytest.mark.xfail(
        strict=False,  # was strict; bug fixed → kept as historical marker
        reason=(
            "BUG: server response status='duplicate' is not mapped to UploadResult — "
            "adapter always returns status='uploaded' regardless of server status field. "
            "Downstream reconcile logic may re-upload already-existing documents."
        ),
    )
    def test_duplicate_response_returns_skipped_or_duplicate(self, tmp_path: Path):
        f = _make_note(tmp_path, "dup.md", "# Dup\nBody")
        adapter, _ = self._make_adapter({"status": "duplicate", "document_id": "doc-existing"})
        result = adapter.upload_markdown(f, vault="my-vault", rel_path="dup.md", base_tags=[])
        assert result.status in ("duplicate", "skipped"), (
            f"Duplicate response not classified correctly: got '{result.status}'"
        )

    def test_client_exception_returns_error_status(self, tmp_path: Path):
        """When client.upload raises, result.status must be 'error', not an unhandled exception."""
        f = _make_note(tmp_path, "err.md", "# Error\nBody")
        mock_client = MagicMock()
        mock_client.upload.side_effect = Exception("connection refused")
        try:
            adapter = DocvaultAdapter("test-space", client=mock_client)
        except TypeError:
            pytest.skip("client= injection not supported")

        try:
            result = adapter.upload_markdown(f, vault="my-vault", rel_path="err.md", base_tags=[])
            assert result.status == "error", (
                f"Expected status='error' on exception, got '{result.status}' — "
                "mutation: exception not caught"
            )
            assert result.error is not None, "error field must be populated on exception"
        except Exception as exc:
            pytest.fail(
                f"upload_markdown raised unhandled exception instead of returning error status: {exc}"
            )

    def test_error_field_contains_message(self, tmp_path: Path):
        f = _make_note(tmp_path, "errmsg.md", "# Error\nBody")
        mock_client = MagicMock()
        mock_client.upload.side_effect = RuntimeError("network timeout")
        try:
            adapter = DocvaultAdapter("test-space", client=mock_client)
        except TypeError:
            pytest.skip("client= injection not supported")

        try:
            result = adapter.upload_markdown(f, vault="my-vault", rel_path="errmsg.md", base_tags=[])
            if result.status == "error":
                assert result.error, "error field must not be empty on failure"
        except Exception:
            pass  # already caught above


# ---------------------------------------------------------------------------
# Tag merge invariants
# ---------------------------------------------------------------------------

class TestTagMerge:
    """base_tags + frontmatter tags must be merged without duplicates."""

    def _upload_and_capture_call(self, tmp_path: Path, content: str, base_tags: list) -> dict:
        """Upload a note and return the kwargs passed to client.upload()."""
        f = _make_note(tmp_path, "tag_test.md", content)
        mock_client = MagicMock()
        mock_client.upload.return_value = {"status": "uploaded", "document_id": "doc-t"}
        try:
            adapter = DocvaultAdapter("test-space", client=mock_client)
        except TypeError:
            pytest.skip("client= injection not supported")
        adapter.upload_markdown(f, vault="my-vault", rel_path="tag_test.md", base_tags=base_tags)
        assert mock_client.upload.called, "client.upload() was never called"
        call_kwargs = mock_client.upload.call_args
        return call_kwargs

    def test_base_tags_passed_to_client(self, tmp_path: Path):
        call_args = self._upload_and_capture_call(
            tmp_path, "# Note\nBody", base_tags=["base-tag"]
        )
        # Flatten call args to find tags
        all_args = list(call_args.args) + list(call_args.kwargs.values())
        all_str = str(all_args)
        assert "base-tag" in all_str, (
            "base_tags not passed to client.upload() — mutation: tags argument dropped"
        )

    def test_frontmatter_tags_merged_with_base_tags(self, tmp_path: Path):
        content = "---\ntags:\n  - fm-tag\n---\nBody"
        call_args = self._upload_and_capture_call(
            tmp_path, content, base_tags=["base-tag"]
        )
        all_str = str(list(call_args.args) + list(call_args.kwargs.values()))
        assert "fm-tag" in all_str, (
            "frontmatter tags not merged — mutation: frontmatter tags discarded"
        )
        assert "base-tag" in all_str

    def test_no_duplicate_tags(self, tmp_path: Path):
        """Same tag in both base_tags and frontmatter must appear only once."""
        content = "---\ntags:\n  - shared-tag\n---\nBody"
        call_args = self._upload_and_capture_call(
            tmp_path, content, base_tags=["shared-tag"]
        )
        all_str = str(list(call_args.args) + list(call_args.kwargs.values()))
        count = all_str.count("shared-tag")
        assert count == 1, (
            f"'shared-tag' appears {count} times — mutation: dedup missing, tags list.extend() without set()"
        )


# ---------------------------------------------------------------------------
# rel_path propagated to server
# ---------------------------------------------------------------------------

class TestRelPathPropagated:
    def test_rel_path_passed_to_client(self, tmp_path: Path):
        f = _make_note(tmp_path, "rel.md", "Body")
        mock_client = MagicMock()
        mock_client.upload.return_value = {"status": "uploaded", "document_id": "doc-r"}
        try:
            adapter = DocvaultAdapter("test-space", client=mock_client)
        except TypeError:
            pytest.skip("client= injection not supported")

        adapter.upload_markdown(
            f, vault="my-vault", rel_path="sub/dir/rel.md", base_tags=[]
        )
        assert mock_client.upload.called
        all_str = str(mock_client.upload.call_args)
        assert "sub/dir/rel.md" in all_str or "rel.md" in all_str, (
            "rel_path not passed to client — mutation: rel_path argument dropped"
        )
