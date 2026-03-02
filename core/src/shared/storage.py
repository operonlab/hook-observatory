"""Shared S3-compatible object storage client — RustFS (MinIO fork) integration.

Used for cold data archiving: large content blobs (reports, briefings) are offloaded
to S3 while metadata stays in PostgreSQL for queryability.

Graceful degradation: returns None when RustFS is unavailable.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Lazy import — aiobotocore is optional; falls back to httpx presigned if unavailable
_session = None


def _get_config():
    from src.config import settings
    return settings


async def _get_client():
    """Get an aiobotocore S3 client. Cached per-process."""
    global _session
    try:
        from aiobotocore.session import AioSession

        config = _get_config()
        if _session is None:
            _session = AioSession()
        ctx = _session.create_client(
            "s3",
            endpoint_url=config.s3_endpoint,
            aws_access_key_id=config.s3_access_key,
            aws_secret_access_key=config.s3_secret_key,
            region_name="us-east-1",
        )
        return ctx
    except ImportError:
        logger.warning("aiobotocore not installed — S3 storage unavailable")
        return None


@asynccontextmanager
async def _s3_client() -> AsyncGenerator:
    """Context manager for S3 client."""
    ctx = await _get_client()
    if ctx is None:
        yield None
        return
    async with ctx as client:
        yield client


async def ensure_bucket(bucket: str | None = None) -> bool:
    """Ensure the archive bucket exists. Creates if missing."""
    bucket = bucket or _get_config().s3_archive_bucket
    async with _s3_client() as client:
        if client is None:
            return False
        try:
            await client.head_bucket(Bucket=bucket)
            return True
        except client.exceptions.ClientError:
            try:
                await client.create_bucket(Bucket=bucket)
                logger.info("Created S3 bucket: %s", bucket)
                return True
            except Exception as e:
                logger.error("Failed to create bucket %s: %s", bucket, e)
                return False
        except Exception as e:
            logger.error("S3 bucket check failed: %s", e)
            return False


async def upload_blob(key: str, data: str | bytes, bucket: str | None = None) -> str | None:
    """Upload a blob to S3. Returns the S3 URI or None on failure.

    Args:
        key: S3 object key (e.g., "intelflow/rpt-abc123")
        data: Content to upload (str or bytes)
        bucket: Override bucket name

    Returns:
        S3 URI like "s3://workshop-archive/intelflow/rpt-abc123" or None
    """
    bucket = bucket or _get_config().s3_archive_bucket
    if isinstance(data, str):
        data = data.encode("utf-8")

    async with _s3_client() as client:
        if client is None:
            return None
        try:
            await client.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType="application/octet-stream",
            )
            return f"s3://{bucket}/{key}"
        except Exception as e:
            logger.error("S3 upload failed for %s: %s", key, e)
            return None


async def download_blob(key: str, bucket: str | None = None) -> str | None:
    """Download a blob from S3. Returns content as string or None.

    Args:
        key: S3 object key
        bucket: Override bucket name

    Returns:
        Content as UTF-8 string or None
    """
    bucket = bucket or _get_config().s3_archive_bucket
    async with _s3_client() as client:
        if client is None:
            return None
        try:
            resp = await client.get_object(Bucket=bucket, Key=key)
            body = await resp["Body"].read()
            return body.decode("utf-8")
        except Exception as e:
            logger.error("S3 download failed for %s: %s", key, e)
            return None


async def delete_blob(key: str, bucket: str | None = None) -> bool:
    """Delete a blob from S3."""
    bucket = bucket or _get_config().s3_archive_bucket
    async with _s3_client() as client:
        if client is None:
            return False
        try:
            await client.delete_object(Bucket=bucket, Key=key)
            return True
        except Exception as e:
            logger.error("S3 delete failed for %s: %s", key, e)
            return False


async def blob_exists(key: str, bucket: str | None = None) -> bool:
    """Check if a blob exists in S3."""
    bucket = bucket or _get_config().s3_archive_bucket
    async with _s3_client() as client:
        if client is None:
            return False
        try:
            await client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False


# ======================== S3 Reference Helpers ========================

S3_REF_PREFIX = "s3://"


def is_s3_ref(value: str | None) -> bool:
    """Check if a value is an S3 reference."""
    return value is not None and value.startswith(S3_REF_PREFIX)


def parse_s3_ref(ref: str) -> tuple[str, str]:
    """Parse S3 URI into (bucket, key)."""
    path = ref[len(S3_REF_PREFIX):]
    bucket, _, key = path.partition("/")
    return bucket, key


async def resolve_content(value: str | None) -> str | None:
    """Transparently resolve content — fetch from S3 if it's a reference.

    If value is a plain string, return as-is.
    If value is an S3 reference, fetch and return the blob content.
    """
    if value is None:
        return None
    if not is_s3_ref(value):
        return value
    bucket, key = parse_s3_ref(value)
    return await download_blob(key, bucket=bucket)
