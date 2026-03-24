"""Freeze engine -- upload cold archives to RustFS (S3-compatible).

Workflow: cold .zst -> upload to S3 -> verify -> update DB -> delete local .zst
Graceful degradation: RustFS offline -> skip freeze, don't fail pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from session_archiver.config import Config

logger = structlog.get_logger(__name__)


def _get_s3_client(config: Config):
    """Create a boto3 S3 client for RustFS. Returns None if unavailable."""
    try:
        import boto3
        from botocore.config import Config as BotoConfig

        client = boto3.client(
            "s3",
            endpoint_url=config.rustfs_endpoint,
            aws_access_key_id=config.rustfs_access_key,
            aws_secret_access_key=config.rustfs_secret_key,
            config=BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
        # Quick connectivity check
        client.list_buckets()
        return client
    except Exception as exc:
        logger.warning("s3_client_unavailable", error=str(exc))
        return None


def ensure_bucket(config: Config) -> bool:
    """Create the freeze bucket if it doesn't exist. Returns True on success."""
    client = _get_s3_client(config)
    if client is None:
        return False

    try:
        existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
        if config.rustfs_bucket not in existing:
            client.create_bucket(Bucket=config.rustfs_bucket)
            logger.info("bucket_created", bucket=config.rustfs_bucket)
        else:
            logger.debug("bucket_exists", bucket=config.rustfs_bucket)
        return True
    except Exception as exc:
        logger.warning("ensure_bucket_failed", error=str(exc))
        return False


def freeze_session(config: Config, session_id: str, dry_run: bool = True) -> dict | None:
    """Freeze a single cold session to RustFS.

    Steps:
      1. Look up session in DB (must be tier='cold')
      2. Check archived_at is older than freeze_min_cold_days
      3. Upload .zst to s3://{bucket}/sessions/{session_id}.jsonl.zst
      4. Verify upload via head_object (size + ETag)
      5. Update DB: tier='frozen', archive_path='s3://...', archive_type='cold-blob'
      6. Log action in archive_log
      7. Delete local .zst file

    Returns result dict on success, None on failure/skip.
    """
    from session_archiver import db

    record = db.get_session(config, session_id)
    if record is None:
        logger.warning("freeze_session_not_found", session_id=session_id)
        return None

    if record.tier != "cold":
        logger.debug("freeze_skip_not_cold", session_id=session_id, tier=record.tier)
        return None

    if not record.archive_path:
        logger.warning("freeze_no_archive_path", session_id=session_id)
        return None

    local_path = Path(record.archive_path)
    if not local_path.exists():
        logger.warning("freeze_local_missing", session_id=session_id, path=str(local_path))
        return None

    s3_key = f"sessions/{session_id}.jsonl.zst"
    s3_uri = f"s3://{config.rustfs_bucket}/{s3_key}"
    local_size = local_path.stat().st_size

    result = {
        "session_id": session_id,
        "local_path": str(local_path),
        "s3_uri": s3_uri,
        "size_bytes": local_size,
        "dry_run": dry_run,
    }

    if dry_run:
        logger.info(
            "freeze_dry_run",
            session_id=session_id,
            size_mb=round(local_size / 1024 / 1024, 2),
            s3_uri=s3_uri,
        )
        return result

    # Upload to S3
    client = _get_s3_client(config)
    if client is None:
        logger.warning("freeze_s3_offline", session_id=session_id)
        return None

    try:
        client.upload_file(str(local_path), config.rustfs_bucket, s3_key)
    except Exception as exc:
        logger.error("freeze_upload_failed", session_id=session_id, error=str(exc))
        return None

    # Verify upload via head_object
    try:
        head = client.head_object(Bucket=config.rustfs_bucket, Key=s3_key)
        remote_size = head["ContentLength"]
        etag = head.get("ETag", "")

        if remote_size != local_size:
            logger.error(
                "freeze_verify_size_mismatch",
                session_id=session_id,
                local=local_size,
                remote=remote_size,
            )
            # Clean up failed upload
            try:
                client.delete_object(Bucket=config.rustfs_bucket, Key=s3_key)
            except Exception:
                pass
            return None

        result["etag"] = etag
    except Exception as exc:
        logger.error("freeze_verify_failed", session_id=session_id, error=str(exc))
        return None

    # Update DB: tier='frozen', archive_path=s3_uri
    db.update_freeze_info(config, session_id, s3_uri, archive_type="cold-blob")
    db.log_action(
        config,
        session_id,
        "freeze",
        "cold",
        "frozen",
        json.dumps({"s3_uri": s3_uri, "size": local_size}),
    )

    # Delete local .zst file
    try:
        local_path.unlink()
        logger.debug("freeze_local_deleted", path=str(local_path))

        # Also delete companion archive if it exists
        companion_archive = local_path.with_suffix("").with_suffix(".companion.tar.zst")
        if companion_archive.exists():
            # Upload companion too
            companion_key = f"sessions/{session_id}.companion.tar.zst"
            try:
                client.upload_file(str(companion_archive), config.rustfs_bucket, companion_key)
                companion_archive.unlink()
                logger.debug("freeze_companion_uploaded", key=companion_key)
            except Exception as exc:
                logger.warning("freeze_companion_upload_failed", error=str(exc))
    except OSError as exc:
        logger.warning("freeze_local_delete_failed", path=str(local_path), error=str(exc))

    logger.info(
        "session_frozen",
        session_id=session_id,
        s3_uri=s3_uri,
        size_mb=round(local_size / 1024 / 1024, 2),
    )
    return result


def freeze_eligible(config: Config, dry_run: bool = True) -> list[dict]:
    """Freeze all cold sessions that are eligible.

    Queries DB for cold sessions older than freeze_min_cold_days,
    then calls freeze_session for each.

    Returns list of result dicts.
    """
    from session_archiver import db

    candidates = db.get_freeze_candidates(config, min_cold_days=config.freeze_min_cold_days)
    if not candidates:
        logger.info("freeze_no_candidates", min_cold_days=config.freeze_min_cold_days)
        return []

    if not dry_run:
        if not ensure_bucket(config):
            logger.warning("freeze_bucket_unavailable")
            return []

    results = []
    for row in candidates:
        try:
            result = freeze_session(config, row["session_id"], dry_run=dry_run)
            if result:
                results.append(result)
        except Exception as exc:
            logger.error(
                "freeze_session_error",
                session_id=row["session_id"],
                error=str(exc),
            )
            continue

    logger.info(
        "freeze_batch_complete",
        candidates=len(candidates),
        frozen=len(results),
        dry_run=dry_run,
    )
    return results
