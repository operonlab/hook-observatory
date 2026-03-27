"""Session Pipeline — orchestrates SessionEnd lifecycle stages.

Stages (in order):
    0. pre-filter — skip trivially empty / command-only sessions
    1. redact   — clean sensitive data from transcript
    2. extract  — memvault knowledge extraction (via extract_async.py)
    3. archive  — session-archiver scan + score
    4. reflect  — quality scoring + context efficiency metrics
    5. log      — observatory event logging

Fail-safe: each stage is wrapped in try/except so failures don't abort the
pipeline.  Exception: if redact FAILS, extract is skipped (never extract
from unredacted data).

Usage:
    from workshop.clients.session_pipeline import SessionPipelineClient

    client = SessionPipelineClient()
    result = client.run_pipeline("abc123")
    print(result.to_dict())
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

HOME = os.path.expanduser("~")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    """Result from a single pipeline stage."""

    name: str
    success: bool = True
    duration_ms: int = 0
    details: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class PipelineResult:
    """Result from running the full pipeline."""

    session_id: str
    transcript_path: str | None = None
    stages: list[StageResult] = field(default_factory=list)
    total_duration_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class SessionPipelineClient:
    """Orchestrates SessionEnd lifecycle: redact → extract → archive → reflect → log.

    Each stage is fail-safe — if one stage fails the pipeline continues with
    the remaining stages, except that a redact failure causes extract to be
    skipped (safety: never extract from unredacted data).

    Args:
        projects_dir: Root dir for Claude projects (default ~/.claude/projects).
        scripts_dir:  memvault scripts directory.
        observatory_url: Hook Observatory base URL (default port_registry).
        core_api_url: Core API base URL (default port_registry).
    """

    def __init__(
        self,
        projects_dir: str | None = None,
        scripts_dir: str | None = None,
        observatory_url: str | None = None,
        core_api_url: str | None = None,
    ) -> None:
        from workshop import port_registry

        self.projects_dir = projects_dir or os.path.expanduser("~/.claude/projects")
        self.scripts_dir = scripts_dir or os.path.expanduser("~/workshop/mcp/memvault/scripts")
        self.observatory_url = (
            observatory_url
            or os.environ.get("HOOK_OBS_URL", port_registry.get_url("hook-observatory"))
        ).rstrip("/")
        self.core_api_url = (
            core_api_url or os.environ.get("CORE_API_URL", port_registry.get_url("core"))
        ).rstrip("/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Stage 0 — Pre-filter
    # ------------------------------------------------------------------

    @staticmethod
    def _should_skip(transcript_path: str | None) -> str | None:
        """Return skip reason if session is trivially empty, else None.

        Skips pipeline for sessions that are clearly not worth processing:
        - File size < 3 KB (empty shells / pure command sessions)
        - Zero real user messages AND < 50 KB (opened-and-closed sessions)

        Does NOT skip headless dispatches (0 user msgs but large files),
        memory auditors / snapshot agents (userType=external, not counted),
        or repair agents (typically > 100 KB).
        """
        if not transcript_path:
            return None
        p = Path(transcript_path)
        if not p.exists():
            return None

        size = p.stat().st_size
        if size < 3_000:
            return f"trivial: file_size={size}B < 3KB"

        # Quick scan first 100 lines for real user messages
        user_msg_count = 0
        lines_read = 0
        try:
            with open(p) as f:
                for line in f:
                    lines_read += 1
                    if lines_read > 100:
                        break
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if obj.get("type") != "user" or obj.get("userType") == "external":
                        continue
                    content = obj.get("message", {}).get("content", "")
                    if isinstance(content, str) and not content.startswith(
                        ("<local-command-", "<command-name>", "<local-command-stdout>")
                    ):
                        if content.strip():
                            user_msg_count += 1
        except OSError:
            return None

        if user_msg_count == 0 and size < 50_000:
            return f"trivial: 0 user messages, size={size}B"

        return None

    def run_pipeline(
        self,
        session_id: str,
        transcript_path: str | None = None,
    ) -> PipelineResult:
        """Run the full SessionEnd pipeline.

        Args:
            session_id:       Claude session ID.
            transcript_path:  Path to transcript JSONL (optional; auto-detected
                              from projects_dir if not provided).

        Returns:
            PipelineResult with per-stage results and timing.
        """
        pipeline_start = time.monotonic()

        # Auto-detect transcript if not provided
        resolved_transcript = transcript_path or self._find_transcript(session_id)

        result = PipelineResult(
            session_id=session_id,
            transcript_path=resolved_transcript,
        )

        # Stage 0 — pre-filter (skip trivially empty sessions)
        skip_reason = self._should_skip(resolved_transcript)
        if skip_reason:
            log.info("pipeline skipped for %s: %s", session_id, skip_reason)
            result.stages.append(
                StageResult(
                    name="pre-filter",
                    success=True,
                    details={"skipped": True, "reason": skip_reason},
                )
            )
            # Still log to observatory so the skip is observable
            log_result = self._stage_log(session_id, result)
            result.stages.append(log_result)
            result.total_duration_ms = int((time.monotonic() - pipeline_start) * 1000)
            return result

        # Stage 1 — redact
        redact_result = self._stage_redact(session_id, resolved_transcript)
        result.stages.append(redact_result)

        # Stage 2 — extract (skip if redact failed for safety)
        if redact_result.success:
            extract_result = self._stage_extract(session_id, resolved_transcript)
        else:
            extract_result = StageResult(
                name="extract",
                success=False,
                error="skipped: redact stage failed (safety policy)",
            )
        result.stages.append(extract_result)

        # Stage 3 — archive (always attempt)
        archive_result = self._stage_archive(session_id)
        result.stages.append(archive_result)

        # Stage 4 — reflect (quality scoring, always attempt)
        reflect_result = self._stage_reflect(session_id, resolved_transcript, result)
        result.stages.append(reflect_result)

        # Stage 5 — log (pass full pipeline result so far)
        log_result = self._stage_log(session_id, result)
        result.stages.append(log_result)

        result.total_duration_ms = int((time.monotonic() - pipeline_start) * 1000)
        return result

    def get_pipeline_config(self) -> dict:
        """Return current pipeline configuration."""
        return {
            "projects_dir": self.projects_dir,
            "scripts_dir": self.scripts_dir,
            "observatory_url": self.observatory_url,
            "extract_script": str(Path(self.scripts_dir) / "extract_async.py"),
        }

    def list_stages(self) -> list[dict]:
        """List all pipeline stages with their status."""
        return [
            {
                "order": 1,
                "name": "redact",
                "description": "Clean sensitive data from transcript",
                "fail_behavior": "skips extract stage",
            },
            {
                "order": 2,
                "name": "extract",
                "description": "memvault knowledge extraction (background)",
                "fail_behavior": "pipeline continues",
            },
            {
                "order": 3,
                "name": "archive",
                "description": "session-archiver scan + score",
                "fail_behavior": "pipeline continues",
            },
            {
                "order": 4,
                "name": "reflect",
                "description": "Quality scoring + context efficiency metrics",
                "fail_behavior": "pipeline continues",
            },
            {
                "order": 5,
                "name": "log",
                "description": "Log pipeline execution to hook observatory",
                "fail_behavior": "pipeline continues",
            },
        ]

    # ------------------------------------------------------------------
    # Private stage implementations
    # ------------------------------------------------------------------

    def _stage_redact(
        self,
        session_id: str,
        transcript_path: str | None,
    ) -> StageResult:
        """Stage 1: Redact sensitive data from transcript."""
        t0 = time.monotonic()
        stage = StageResult(name="redact")
        try:
            from workshop.clients.session_redactor import (
                SessionRedactorClient,  # type: ignore[import]
            )

            client = SessionRedactorClient()
            if transcript_path:
                # Targeted: redact the specific transcript file
                result = client.redact_file(transcript_path, trigger="hook", session_id=session_id)
                outcome = result.to_dict()
            else:
                # No transcript path — nothing to redact for this session
                outcome = {"skipped": True, "reason": "no transcript_path provided"}
            stage.details = outcome if isinstance(outcome, dict) else {"result": str(outcome)}
        except ImportError:
            # session_redactor SDK not available — fall back to legacy shell script
            script = (
                Path(HOME)
                / "Claude"
                / "projects"
                / "session-redactor"
                / "scripts"
                / "redact-session.sh"
            )
            if not script.exists():
                stage.success = False
                stage.error = f"session_redactor SDK not found and shell script missing at {script}"
            else:
                try:
                    payload = json.dumps(
                        {"session_id": session_id, "transcript_path": transcript_path}
                    )
                    proc = subprocess.run(  # noqa: S603
                        [str(script)],
                        input=payload,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if proc.returncode != 0:
                        stage.success = False
                        stage.error = proc.stderr.strip() or f"exit {proc.returncode}"
                    else:
                        stage.details = {"output": proc.stdout.strip()[:500]}
                except Exception as exc:
                    stage.success = False
                    stage.error = str(exc)
        except Exception as exc:
            stage.success = False
            stage.error = str(exc)
            log.warning("redact stage error: %s", exc)
        finally:
            stage.duration_ms = int((time.monotonic() - t0) * 1000)
        return stage

    def _stage_extract(
        self,
        session_id: str,
        transcript_path: str | None,
    ) -> StageResult:
        """Stage 2: Extract knowledge via memvault (background process).

        Spawns extract_async.py as a detached subprocess. The script
        uses LLM internally for semantic extraction — this SDK method is
        purely a launcher and does not perform any LLM reasoning itself.
        """
        t0 = time.monotonic()
        stage = StageResult(name="extract")
        try:
            script = Path(self.scripts_dir) / "extract_async.py"
            if not script.exists():
                stage.success = False
                stage.error = f"extract script not found: {script}"
            else:
                payload = json.dumps({"session_id": session_id, "transcript_path": transcript_path})
                # Async / background — mirrors existing external.extract handler.
                # stderr goes to log file for debuggability (not DEVNULL).
                log_path = Path(HOME) / ".claude" / "data" / "session-pipeline" / "extract.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    stderr_fh = open(log_path, "a")
                except OSError as e:
                    raise RuntimeError(f"failed to open extract log {log_path}: {e}") from e
                proc = subprocess.Popen(  # noqa: S603
                    [sys.executable, str(script)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr_fh,
                    start_new_session=True,
                )
                stderr_fh.close()
                try:
                    proc.stdin.write(payload.encode())
                finally:
                    proc.stdin.close()
                stage.details = {"pid": proc.pid, "mode": "background", "log": str(log_path)}
        except Exception as exc:
            stage.success = False
            stage.error = str(exc)
            log.warning("extract stage error: %s", exc)
        finally:
            stage.duration_ms = int((time.monotonic() - t0) * 1000)
        return stage

    def _stage_archive(self, session_id: str) -> StageResult:
        """Stage 3: Scan and score for archival via session-archiver."""
        t0 = time.monotonic()
        stage = StageResult(name="archive")
        try:
            from workshop.clients.session_archiver import (
                SessionArchiverClient,
            )

            client = SessionArchiverClient()
            scan_result = client.scan(session_id=session_id)
            stage.details = {
                "scanned": scan_result.get("scanned", 0),
                "upserted": scan_result.get("upserted", 0),
            }
        except Exception as exc:
            stage.success = False
            stage.error = str(exc)
            log.warning("archive stage error: %s", exc)
        finally:
            stage.duration_ms = int((time.monotonic() - t0) * 1000)
        return stage

    def _stage_reflect(
        self,
        session_id: str,
        transcript_path: str | None,
        pipeline_result: PipelineResult,
    ) -> StageResult:
        """Stage 4: Quality scoring + context efficiency metrics.

        Parses the transcript JSONL with reflect_engine (pure-function, no LLM),
        writes results to session_archiver DB, and optionally feeds high-quality
        sessions back to memvault via HTTP (quality_score > 0.6).

        Fail-safe: exceptions do not propagate; prior stages are unaffected.
        """
        t0 = time.monotonic()
        stage = StageResult(name="reflect")
        try:
            # ------------------------------------------------------------------
            # Import reflect_engine from stations/session-pipeline/
            # ------------------------------------------------------------------
            _engine_dir = os.path.expanduser("~/workshop/stations/session-pipeline")
            if _engine_dir not in sys.path:
                sys.path.insert(0, _engine_dir)

            from reflect_engine import ReflectMetrics, analyze_transcript  # type: ignore[import]

            # ------------------------------------------------------------------
            # Analyze transcript (pure-function, no LLM)
            # ------------------------------------------------------------------
            if transcript_path:
                metrics: ReflectMetrics = analyze_transcript(transcript_path, session_id)
            else:
                # No transcript available — create minimal metrics
                from datetime import UTC, datetime

                metrics = ReflectMetrics(
                    session_id=session_id,
                    outcome="unknown",
                    quality_score=0.0,
                    reflected_at=datetime.now(UTC).isoformat(),
                )

            # ------------------------------------------------------------------
            # Count prior pipeline stage outcomes
            # ------------------------------------------------------------------
            stages_ok = sum(1 for s in pipeline_result.stages if s.success)
            stages_fail = sum(1 for s in pipeline_result.stages if not s.success)
            metrics.pipeline_stages_ok = stages_ok
            metrics.pipeline_stages_fail = stages_fail

            # ------------------------------------------------------------------
            # Persist to DB via session-archiver config
            # ------------------------------------------------------------------
            db_written = False
            try:
                import sys as _sys

                _archiver_src = os.path.expanduser("~/workshop/stations/session-archiver/src")
                if _archiver_src not in _sys.path:
                    _sys.path.insert(0, _archiver_src)

                from session_archiver.config import (
                    load_config as _load_archiver_config,  # type: ignore[import]
                )
                from session_archiver.db import upsert_reflection  # type: ignore[import]

                archiver_cfg = _load_archiver_config()
                db_written = upsert_reflection(archiver_cfg, metrics.to_dict())
            except Exception as db_exc:
                log.warning("reflect db write failed (non-fatal): %s", db_exc)

            # ------------------------------------------------------------------
            # Feed high-quality sessions back to memvault (quality_score > 0.6)
            #
            # NOTE: The /api/memvault/reflect route requires auth (session cookie).
            # The background pipeline has no session cookie, so HTTP POST would
            # always receive 401.  Instead, call reflect_on_session() directly
            # (pure function, no DB/auth needed) to obtain invariant/derived
            # counts for this pipeline run, then mark the KG write-back as
            # deferred — the weekly GRC runner will perform the full write-back
            # with a proper authenticated context.
            # ------------------------------------------------------------------
            if metrics.quality_score > 0.6:
                try:
                    import importlib.util

                    # Load reflection.py directly via importlib to avoid triggering
                    # memvault/__init__.py which imports fastapi (not available in
                    # the background pipeline's Python env).
                    _refl_path = os.path.expanduser(
                        "~/workshop/core/src/modules/memvault/reflection.py"
                    )
                    _core_src = os.path.expanduser("~/workshop/core/src")
                    if _core_src not in sys.path:
                        sys.path.insert(0, _core_src)
                    _spec = importlib.util.spec_from_file_location(
                        "memvault_reflection",
                        _refl_path,
                        submodule_search_locations=[],
                    )
                    _mod = importlib.util.module_from_spec(_spec)
                    sys.modules[_spec.name] = _mod  # register so @dataclass works
                    _spec.loader.exec_module(_mod)
                    _reflect_on_session = _mod.reflect_on_session

                    # Load memory blocks from the transcript (best-effort).
                    # reflect_on_session is a pure function — no DB required.
                    _blocks: list[dict] = []
                    if transcript_path:
                        try:
                            import json as _json2

                            with open(transcript_path) as _tf:
                                for _line in _tf:
                                    _line = _line.strip()
                                    if not _line:
                                        continue
                                    try:
                                        _entry = _json2.loads(_line)
                                        # Extract assistant text content as pseudo-blocks
                                        if _entry.get("type") == "assistant":
                                            for _msg in _entry.get("message", {}).get(
                                                "content", []
                                            ):
                                                if (
                                                    isinstance(_msg, dict)
                                                    and _msg.get("type") == "text"
                                                ):
                                                    _blocks.append(
                                                        {
                                                            "content": _msg["text"],
                                                            "block_type": "observation",
                                                            "tags": [],
                                                        }
                                                    )
                                    except Exception:  # noqa: S110
                                        pass
                        except Exception:  # noqa: S110
                            pass

                    _ref_result = _reflect_on_session(_blocks, session_id=session_id)
                    metrics.invariant_count = len(_ref_result.invariants)
                    metrics.derived_count = len(_ref_result.derived)
                    # KG write-back deferred — the weekly GRC runner will persist
                    # invariants/derived to DB with proper auth context.
                    metrics.reflection_fed = True  # analysis done, write-back deferred
                    log.info(
                        "reflect: pure analysis done (KG write-back deferred) "
                        "invariants=%d derived=%d session=%s",
                        metrics.invariant_count,
                        metrics.derived_count,
                        session_id,
                    )
                except Exception as mv_exc:
                    log.info("memvault reflect skipped (non-fatal): %s", mv_exc)

            stage.details = {
                "outcome": metrics.outcome,
                "quality_score": metrics.quality_score,
                "tool_success_rate": metrics.tool_success_rate,
                "context_efficiency": metrics.context_efficiency,
                "turn_count": metrics.turn_count,
                "total_tokens": metrics.total_tokens,
                "db_written": db_written,
                "reflection_fed": metrics.reflection_fed,
                "invariant_count": metrics.invariant_count,
                "derived_count": metrics.derived_count,
                "failure_patterns": metrics.failure_patterns,
            }
        except Exception as exc:
            stage.success = False
            stage.error = str(exc)
            log.warning("reflect stage error: %s", exc)
        finally:
            stage.duration_ms = int((time.monotonic() - t0) * 1000)
        return stage

    def _stage_log(
        self,
        session_id: str,
        pipeline_result: PipelineResult,
    ) -> StageResult:
        """Stage 4: Log pipeline execution to hook observatory."""
        t0 = time.monotonic()
        stage = StageResult(name="log")
        try:
            # Build a compact summary so we don't POST megabytes of data
            stages_summary = [
                {"name": s.name, "success": s.success, "duration_ms": s.duration_ms}
                for s in pipeline_result.stages
            ]
            payload = {
                "event_type": "SessionPipeline",
                "session_id": session_id,
                "data": {
                    "transcript_path": pipeline_result.transcript_path,
                    "stages": stages_summary,
                    "total_duration_ms": pipeline_result.total_duration_ms,
                },
            }
            try:
                import httpx

                resp = httpx.post(
                    f"{self.observatory_url}/api/events",
                    json=payload,
                    headers={
                        "x-local-key": os.environ.get("HOOK_OBS_SECRET_KEY", "workshop-v2-dev-key")
                    },
                    timeout=5,
                )
                stage.details = {"status_code": resp.status_code}
                if resp.status_code >= 400:
                    # Non-fatal — observatory may be offline
                    stage.success = False
                    stage.error = f"observatory returned {resp.status_code}"
            except Exception:
                # Observatory offline — fall back to local log
                log.info(
                    "session_pipeline completed (observatory offline): %s",
                    json.dumps(stages_summary),
                )
                stage.details = {"fallback": "local_log"}
        except Exception as exc:
            stage.success = False
            stage.error = str(exc)
            log.warning("log stage error: %s", exc)
        finally:
            stage.duration_ms = int((time.monotonic() - t0) * 1000)
        return stage

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_transcript(self, session_id: str) -> str | None:
        """Try to locate the transcript JSONL for a given session_id."""
        projects = Path(self.projects_dir)
        if not projects.exists():
            return None
        # Claude stores sessions under ~/.claude/projects/<project_hash>/sessions/<session_id>.jsonl
        for candidate in projects.rglob(f"{session_id}.jsonl"):
            return str(candidate)
        # Partial match fallback (first 8 chars)
        if len(session_id) >= 8:
            prefix = session_id[:8]
            for candidate in projects.rglob(f"{prefix}*.jsonl"):
                return str(candidate)
        return None
