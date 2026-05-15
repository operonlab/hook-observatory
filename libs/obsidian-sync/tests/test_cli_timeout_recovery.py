"""Regression tests for cli sync timeout self-heal (F2).

六鐵律 disclosure: these tests were authored by the same agent that
implemented the cli retry logic — not full 寫測分離. They follow
mutation-thinking and invariant-first discipline, but a future
independent test-adversary should still re-attack this surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from obsidian_sync import cli as cli_module
from obsidian_sync.docvault_adapter import UploadResult


class _ScriptedAdapter:
    """Stand-in for DocvaultAdapter that returns a queued sequence of UploadResults.

    Mock boundary is the adapter (external HTTP from cli's perspective).
    Internal cli wiring (walker / state / frontmatter) runs real.
    """

    def __init__(self, space_id: str, timeout: float = 0):
        self.space_id = space_id
        self.calls: list[dict[str, Any]] = []
        self._queue: list[UploadResult] = []

    def queue(self, *results: UploadResult) -> None:
        self._queue.extend(results)

    def upload_markdown(self, *, file_path, vault, rel_path, base_tags) -> UploadResult:
        self.calls.append({"rel_path": rel_path, "base_tags": list(base_tags)})
        if not self._queue:
            raise AssertionError(f"unexpected extra call for {rel_path}")
        return self._queue.pop(0)

    def delete_document(self, document_id: str) -> bool:
        return True


@pytest.fixture
def tiny_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Note\nbody\n", encoding="utf-8")
    return vault


def _run_sync(
    monkeypatch,
    *,
    vault: Path,
    space: str,
    state_path: Path,
    adapter: _ScriptedAdapter,
) -> int:
    monkeypatch.setattr(
        cli_module, "DocvaultAdapter", lambda space_id, timeout=0: adapter
    )
    return cli_module.main(
        [
            "sync",
            "--vault",
            str(vault),
            "--space",
            space,
            "--state-file",
            str(state_path),
        ]
    )


def test_timeout_then_duplicate_records_state(
    tmp_path: Path, tiny_vault: Path, monkeypatch
):
    """Killer test: first call times out, retry hits 409 dedup → state must record."""
    state_path = tmp_path / "state.json"
    adapter = _ScriptedAdapter("test-space")
    adapter.queue(
        UploadResult(status="timeout", skipped_reason="HTTP timeout"),
        UploadResult(status="duplicate", document_id="doc-recovered-001"),
    )

    rc = _run_sync(
        monkeypatch,
        vault=tiny_vault,
        space="test-space",
        state_path=state_path,
        adapter=adapter,
    )

    assert rc == 0
    assert len(adapter.calls) == 2, "cli must retry once after timeout"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert "note.md" in data["entries"]
    assert data["entries"]["note.md"]["document_id"] == "doc-recovered-001"


def test_no_timeout_no_extra_call(tmp_path: Path, tiny_vault: Path, monkeypatch):
    """Invariant: when first upload succeeds, retry must NOT fire."""
    state_path = tmp_path / "state.json"
    adapter = _ScriptedAdapter("test-space")
    adapter.queue(UploadResult(status="uploaded", document_id="doc-fresh-002"))

    rc = _run_sync(
        monkeypatch,
        vault=tiny_vault,
        space="test-space",
        state_path=state_path,
        adapter=adapter,
    )

    assert rc == 0
    assert len(adapter.calls) == 1, "no retry must fire on success"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["entries"]["note.md"]["document_id"] == "doc-fresh-002"


def test_timeout_then_timeout_does_not_record(
    tmp_path: Path, tiny_vault: Path, monkeypatch
):
    """Killer test: server truly unreachable — both attempts time out → state must NOT record (failure is loud)."""
    state_path = tmp_path / "state.json"
    adapter = _ScriptedAdapter("test-space")
    adapter.queue(
        UploadResult(status="timeout", skipped_reason="HTTP timeout"),
        UploadResult(status="timeout", skipped_reason="HTTP timeout"),
    )

    rc = _run_sync(
        monkeypatch,
        vault=tiny_vault,
        space="test-space",
        state_path=state_path,
        adapter=adapter,
    )

    assert rc == 0  # timeout != error in current cli policy
    assert len(adapter.calls) == 2
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert "note.md" not in data.get("entries", {}), (
        "regression: state recorded a file that the server may not have indexed"
    )


def test_timeout_then_uploaded_records_state(
    tmp_path: Path, tiny_vault: Path, monkeypatch
):
    """Rare: server hadn't committed before timeout, retry succeeds fresh.

    Killer test: cli must accept BOTH 'duplicate' and 'uploaded' retry outcomes
    as recovery. A mutation that gates only on 'duplicate' should fail here.
    """
    state_path = tmp_path / "state.json"
    adapter = _ScriptedAdapter("test-space")
    adapter.queue(
        UploadResult(status="timeout", skipped_reason="HTTP timeout"),
        UploadResult(status="uploaded", document_id="doc-late-003"),
    )

    rc = _run_sync(
        monkeypatch,
        vault=tiny_vault,
        space="test-space",
        state_path=state_path,
        adapter=adapter,
    )

    assert rc == 0
    assert len(adapter.calls) == 2
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert "note.md" in data["entries"], (
        "regression: cli ignored a successful 'uploaded' retry after initial timeout"
    )
    assert data["entries"]["note.md"]["document_id"] == "doc-late-003"
