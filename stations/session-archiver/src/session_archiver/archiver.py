"""Archive engine — zstd compression + stub generation + DB writes.

Handles the core archive workflow:
1. Compress JSONL with zstd
2. Compress companion dir if exists
3. Verify compressed file integrity
4. Write metadata stub to original location
5. Update DB records
6. Remove original files after verification
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import structlog

from session_archiver.config import Config
from session_archiver.models import ScoreBreakdown, SessionMeta

logger = structlog.get_logger(__name__)


def _ensure_archive_dir(config: Config) -> Path:
    """Ensure the archive directory exists."""
    archive_dir = Path(config.archive_dir).expanduser()
    archive_dir.mkdir(parents=True, exist_ok=True)
    return archive_dir


def _compress_file(src: Path, dst: Path, level: int = 9) -> bool:
    """Compress a file using zstd. Returns True on success."""
    try:
        result = subprocess.run(
            ["zstd", f"-{level}", "--rm", str(src), "-o", str(dst)],
            capture_output=True,
            text=True,
        )
        # --rm removes source only on success, but we handle removal ourselves
        # Actually don't use --rm, we verify first then remove manually
        if result.returncode != 0:
            logger.error("zstd_compress_failed", src=str(src), stderr=result.stderr[:200])
            return False
        return True
    except FileNotFoundError:
        logger.error("zstd_not_found")
        return False
    except OSError as e:
        logger.error("compress_error", error=str(e))
        return False


def _compress_file_safe(src: Path, dst: Path, level: int = 9) -> bool:
    """Compress without removing source (we verify first, then remove manually)."""
    try:
        result = subprocess.run(
            ["zstd", f"-{level}", str(src), "-o", str(dst)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("zstd_compress_failed", src=str(src), stderr=result.stderr[:200])
            return False
        return True
    except FileNotFoundError:
        logger.error("zstd_not_found")
        return False
    except OSError as e:
        logger.error("compress_error", error=str(e))
        return False


def _compress_companion(companion_path: Path, dst: Path, level: int = 9) -> bool:
    """Compress companion directory: tar | zstd."""
    try:
        # Two-step pipeline (shell=False prevents injection): tar → zstd via stdin/stdout
        tar_proc = subprocess.Popen(
            ["tar", "cf", "-", "-C", str(companion_path.parent), companion_path.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        zstd_proc = subprocess.Popen(
            ["zstd", f"-{level}", "-o", str(dst)],
            stdin=tar_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Allow tar to receive SIGPIPE if zstd exits early
        if tar_proc.stdout:
            tar_proc.stdout.close()
        _, zstd_err = zstd_proc.communicate()
        tar_proc.wait()
        if tar_proc.returncode != 0 or zstd_proc.returncode != 0:
            logger.error(
                "companion_compress_failed",
                tar_rc=tar_proc.returncode,
                zstd_rc=zstd_proc.returncode,
                stderr=zstd_err.decode()[:200],
            )
            return False
        return True
    except FileNotFoundError as e:
        logger.error("companion_compress_tool_not_found", error=str(e))
        return False
    except OSError as e:
        logger.error("companion_compress_error", error=str(e))
        return False


def _verify_archive(archive_path: Path) -> bool:
    """Verify compressed file integrity with zstd -t."""
    try:
        result = subprocess.run(
            ["zstd", "-t", str(archive_path)],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except (FileNotFoundError, OSError):
        return False


def _write_stub(
    original_path: Path,
    meta: SessionMeta,
    score: ScoreBreakdown,
    archive_path: Path,
    compressed_size: int,
    compression_ratio: float,
    summary: str | None,
) -> bool:
    """Write archived metadata stub JSON to original location."""
    stub_path = original_path.with_suffix(".archived.json")
    stub = {
        "_type": "archived-session",
        "sessionId": meta.session_id,
        "tier": "cold",
        "archiveType": "cold-archive",
        "archivedAt": datetime.now(UTC).isoformat(),
        "originalSize": meta.file_size_bytes,
        "compressedSize": compressed_size,
        "compressionRatio": round(compression_ratio, 4),
        "archivePath": str(archive_path),
        "summary": summary,
        "firstTimestamp": meta.first_timestamp,
        "lastTimestamp": meta.last_timestamp,
        "eventCount": meta.event_count,
        "turnCount": meta.turn_count,
        "score": round(score.total, 1),
        "thawCommand": f"session-archiver thaw {meta.session_id[:8]}",
    }
    try:
        with open(stub_path, "w", encoding="utf-8") as f:
            json.dump(stub, f, indent=2, ensure_ascii=False)
        return True
    except OSError as e:
        logger.error("write_stub_failed", path=str(stub_path), error=str(e))
        return False


def _remove_original(jsonl_path: Path, companion_path: Path | None) -> bool:
    """Remove original JSONL and companion directory after successful archive."""
    import shutil

    try:
        jsonl_path.unlink(missing_ok=True)
        if companion_path and companion_path.is_dir():
            shutil.rmtree(companion_path)
        return True
    except OSError as e:
        logger.error("remove_original_failed", error=str(e))
        return False


def archive_session(
    config: Config,
    meta: SessionMeta,
    score: ScoreBreakdown,
    summary: str | None = None,
    dry_run: bool = True,
) -> dict | None:
    """Archive a single session.

    Returns archive result dict on success, None on failure.
    If dry_run=True, returns what would happen without actually archiving.
    """
    archive_dir = _ensure_archive_dir(config)
    archive_path = archive_dir / f"{meta.session_id}.jsonl.zst"
    companion_archive = archive_dir / f"{meta.session_id}.companion.tar.zst"

    result = {
        "session_id": meta.session_id,
        "original_size": meta.file_size_bytes,
        "archive_path": str(archive_path),
        "dry_run": dry_run,
    }

    if dry_run:
        logger.info("dry_run_archive", session_id=meta.session_id,
                     size_mb=round(meta.file_size_bytes / 1024 / 1024, 1),
                     score=round(score.total, 1))
        return result

    # Step 1: Compress JSONL
    if not meta.jsonl_path.exists():
        logger.error("jsonl_not_found", path=str(meta.jsonl_path))
        return None

    # Guard against re-archiving a session whose .zst already exists in cold/.
    # Means a prior archive run wrote the zst but DB/stub steps did not complete
    # (or this is a stub the candidate filter let slip). Reconcile DB and skip
    # compression rather than silently failing on "Not overwritten" prompt.
    if archive_path.exists():
        logger.warning(
            "archive_target_exists_reconciling",
            session_id=meta.session_id,
            archive_path=str(archive_path),
        )
        from session_archiver import db

        existing_size = archive_path.stat().st_size
        ratio = 1 - (existing_size / max(meta.file_size_bytes, 1))
        db.update_archive_info(
            config, meta.session_id, str(archive_path),
            "cold-archive", existing_size, ratio,
        )
        result.update({
            "compressed_size": existing_size,
            "compression_ratio": round(ratio, 4),
            "companion_archived": companion_archive.exists(),
            "saved_bytes": meta.file_size_bytes - existing_size,
            "reconciled": True,
        })
        return result

    if not _compress_file_safe(meta.jsonl_path, archive_path, config.compression_level):
        return None

    # Step 2: Compress companion if exists
    has_companion_archive = False
    if meta.has_companion and meta.companion_path and meta.companion_path.is_dir():
        has_companion_archive = _compress_companion(
            meta.companion_path, companion_archive, config.compression_level
        )

    # Step 3: Verify
    if not _verify_archive(archive_path):
        logger.error("verification_failed", archive=str(archive_path))
        archive_path.unlink(missing_ok=True)
        return None

    compressed_size = archive_path.stat().st_size
    compression_ratio = 1 - (compressed_size / max(meta.file_size_bytes, 1))

    # Step 4: Write stub
    _write_stub(
        meta.jsonl_path, meta, score, archive_path,
        compressed_size, compression_ratio, summary,
    )

    # Step 5: Update DB (graceful — failure doesn't block archive)
    from session_archiver import db

    db.update_archive_info(
        config, meta.session_id, str(archive_path),
        "cold-archive", compressed_size, compression_ratio,
    )
    db.log_action(config, meta.session_id, "archive", "hot", "cold",
                  json.dumps({"compressed_size": compressed_size,
                              "ratio": round(compression_ratio, 4)}))

    # Step 6: Remove originals (only after verify passes)
    _remove_original(meta.jsonl_path, meta.companion_path if meta.has_companion else None)

    result.update({
        "compressed_size": compressed_size,
        "compression_ratio": round(compression_ratio, 4),
        "companion_archived": has_companion_archive,
        "saved_bytes": meta.file_size_bytes - compressed_size,
    })

    logger.info("session_archived",
                session_id=meta.session_id,
                original_mb=round(meta.file_size_bytes / 1024 / 1024, 1),
                compressed_mb=round(compressed_size / 1024 / 1024, 1),
                ratio=f"{compression_ratio:.1%}")

    return result


def archive_batch(
    config: Config,
    candidates: list[tuple[SessionMeta, ScoreBreakdown]],
    summaries: dict[str, str | None] | None = None,
    dry_run: bool = True,
) -> list[dict]:
    """Archive a batch of sessions. Each session is independent (P5 non-blocking).

    Returns list of result dicts (one per session).
    """
    summaries = summaries or {}
    results = []

    for meta, score in candidates:
        try:
            result = archive_session(
                config, meta, score,
                summary=summaries.get(meta.session_id),
                dry_run=dry_run,
            )
            if result:
                results.append(result)
        except Exception as e:
            # P5: individual failure doesn't block others
            logger.error("archive_session_error", session_id=meta.session_id, error=str(e))
            continue

    return results
