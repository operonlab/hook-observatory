"""Thaw engine — decompress archived sessions back to hot tier.

Workflow:
1. Look up archive_path in DB or read local stub
2. Decompress JSONL with zstd
3. Decompress companion if exists
4. Update DB: tier='hot', thaw_count += 1
5. Remove .archived.json stub
6. Log to archive_log
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import structlog

from session_archiver.config import Config

logger = structlog.get_logger(__name__)


def _find_stub(projects_dir: str, session_id_prefix: str) -> dict | None:
    """Find an archived stub by session_id prefix in projects directory."""
    base = Path(projects_dir).expanduser()
    for stub_path in base.rglob("*.archived.json"):
        try:
            with open(stub_path) as f:
                stub = json.load(f)
            if stub.get("sessionId", "").startswith(session_id_prefix):
                stub["_stub_path"] = str(stub_path)
                return stub
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _decompress_file(src: Path, dst: Path) -> bool:
    """Decompress a zstd file."""
    try:
        result = subprocess.run(
            ["zstd", "-d", str(src), "-o", str(dst)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("zstd_decompress_failed", src=str(src), stderr=result.stderr[:200])
            return False
        return True
    except (FileNotFoundError, OSError) as e:
        logger.error("decompress_error", error=str(e))
        return False


def _decompress_companion(src: Path, dest_dir: Path) -> bool:
    """Decompress companion archive: zstd -d | tar xf."""
    try:
        result = subprocess.run(
            f'zstd -d "{src}" --stdout | tar xf - -C "{dest_dir}"',
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("companion_decompress_failed", stderr=result.stderr[:200])
            return False
        return True
    except OSError as e:
        logger.error("companion_decompress_error", error=str(e))
        return False


def _download_from_s3(config: Config, s3_uri: str, local_path: Path) -> bool:
    """Download a file from S3 (RustFS) to local path. Returns True on success."""
    from session_archiver.freezer import _get_s3_client

    client = _get_s3_client(config)
    if client is None:
        logger.error("thaw_s3_client_unavailable")
        return False

    try:
        # Parse s3://bucket/key
        without_prefix = s3_uri.removeprefix("s3://")
        bucket, _, key = without_prefix.partition("/")

        local_path.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(bucket, key, str(local_path))
        logger.info("s3_downloaded", s3_uri=s3_uri, local=str(local_path))
        return True
    except Exception as exc:
        logger.error("s3_download_failed", s3_uri=s3_uri, error=str(exc))
        return False


def thaw_session(config: Config, session_id_prefix: str) -> dict | None:
    """Thaw (restore) an archived session.

    Supports both cold (local .zst) and frozen (S3) tiers.
    Frozen sessions are downloaded from S3 to local cold dir first,
    then decompressed normally.

    Args:
        config: Configuration
        session_id_prefix: Full or partial session ID (minimum 8 chars)

    Returns:
        Result dict on success, None on failure
    """
    from session_archiver import db

    # Step 1: Find the session -- try DB first, then local stub
    record = None
    full_session_id = None
    archive_path = None
    project_path = None
    stub_path = None
    from_tier = "cold"

    record = db.get_session(config, session_id_prefix)
    if record and record.archive_path:
        full_session_id = record.session_id
        archive_path_str = record.archive_path
        project_path = record.project_path

        # Handle frozen tier: download from S3 first
        if record.tier == "frozen" and archive_path_str.startswith("s3://"):
            from_tier = "frozen"
            cold_dir = Path(config.archive_dir).expanduser()
            cold_dir.mkdir(parents=True, exist_ok=True)
            local_zst = cold_dir / f"{full_session_id}.jsonl.zst"

            if not _download_from_s3(config, archive_path_str, local_zst):
                return None

            # Also try to download companion
            companion_s3 = archive_path_str.replace(".jsonl.zst", ".companion.tar.zst")
            local_companion = cold_dir / f"{full_session_id}.companion.tar.zst"
            _download_from_s3(config, companion_s3, local_companion)
            # Non-fatal if companion doesn't exist

            archive_path = local_zst
        else:
            archive_path = Path(archive_path_str)
    else:
        # Fallback: scan for local stub
        stub = _find_stub(config.projects_dir, session_id_prefix)
        if stub:
            full_session_id = stub["sessionId"]
            archive_path = Path(stub["archivePath"]).expanduser()
            stub_path = stub.get("_stub_path")
            # Derive project_path from stub location
            stub_p = Path(stub_path)
            projects_base = Path(config.projects_dir).expanduser()
            try:
                rel = stub_p.parent.relative_to(projects_base)
                project_path = str(rel.parts[0]) if rel.parts else ""
            except ValueError:
                project_path = ""

    if not full_session_id or not archive_path:
        logger.error("session_not_found", prefix=session_id_prefix)
        return None

    if not archive_path.exists():
        logger.error("archive_file_missing", path=str(archive_path))
        return None

    # Step 2: Determine restore destination
    projects_base = Path(config.projects_dir).expanduser()
    if project_path:
        dest_dir = projects_base / project_path
    else:
        dest_dir = projects_base

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_jsonl = dest_dir / f"{full_session_id}.jsonl"

    # Step 3: Decompress JSONL
    if not _decompress_file(archive_path, dest_jsonl):
        return None

    # Step 4: Decompress companion if exists
    companion_archive = archive_path.with_suffix("").with_suffix(".companion.tar.zst")
    companion_restored = False
    if companion_archive.exists():
        companion_restored = _decompress_companion(companion_archive, dest_dir)

    # Step 5: Update DB
    db.update_thaw(config, full_session_id)
    db.log_action(config, full_session_id, "thaw", from_tier, "hot")

    # Step 6: Remove stub
    if stub_path:
        Path(stub_path).unlink(missing_ok=True)
    else:
        # Find and remove stub by session ID
        for p in dest_dir.glob("*.archived.json"):
            try:
                with open(p) as f:
                    s = json.load(f)
                if s.get("sessionId") == full_session_id:
                    p.unlink()
                    break
            except (json.JSONDecodeError, OSError):
                continue

    # Step 7: Clean up downloaded S3 files (they are now decompressed)
    if from_tier == "frozen":
        archive_path.unlink(missing_ok=True)
        if companion_archive.exists():
            companion_archive.unlink(missing_ok=True)

    result = {
        "session_id": full_session_id,
        "restored_to": str(dest_jsonl),
        "companion_restored": companion_restored,
        "from_tier": from_tier,
        "resume_command": f"claude --resume {full_session_id}",
    }

    logger.info("session_thawed", **result)
    return result
