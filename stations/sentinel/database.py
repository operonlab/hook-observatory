"""Async database engine + JSONL spool fallback."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import config

logger = logging.getLogger(__name__)

# ── SQL Injection Guard ───────────────────────────────────────
# Whitelist of allowed tables and their permitted column names.
# Any persist() call with an unknown table or column is rejected.
ALLOWED_TABLES: dict[str, frozenset[str]] = {
    "health_checks": frozenset({
        "id", "service", "check_type", "status",
        "response_ms", "detail", "created_at",
    }),
    "incidents": frozenset({
        "id", "service", "status", "severity",
        "title", "detail", "created_at",
    }),
    "active_operations": frozenset({
        "id", "service", "action", "agent_id",
        "pid", "estimated_duration", "created_at",
    }),
    "subscriptions": frozenset({
        "id", "url", "events", "active", "created_at",
    }),
}

engine = create_async_engine(
    config.database_url,
    pool_size=5,
    max_overflow=5,
    echo=False,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    """FastAPI dependency — yields an async DB session."""
    async with async_session() as session:
        yield session


# ── JSONL Spool Fallback ──────────────────────────────────────


class SpoolWriter:
    """Fire-and-forget JSONL writer for when PG is down."""

    def __init__(self, spool_dir: Path):
        self.spool_dir = spool_dir
        self._file = self.spool_dir / "spool.jsonl"
        self._dir_ensured = False

    def _ensure_dir(self) -> None:
        if not self._dir_ensured:
            try:
                self.spool_dir.mkdir(parents=True, exist_ok=True)
                self._dir_ensured = True
            except OSError:
                pass

    def append(self, record: dict) -> None:
        """Sync append — called from except block, must not fail."""
        self._ensure_dir()
        try:
            record["_spooled_at"] = datetime.now(UTC).isoformat()
            with open(self._file, "a") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            logger.exception("Spool write failed")

    async def drain(self, writer_fn) -> int:
        """Drain spool to PG. Returns number of records drained."""
        if not self._file.exists() or self._file.stat().st_size == 0:
            return 0

        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        draining = self.spool_dir / f"spool-{ts}.draining"

        try:
            self._file.rename(draining)
        except FileNotFoundError:
            return 0

        records = []
        with Path.open(draining) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Malformed spool line, skipping")

        if records:
            try:
                await writer_fn(records)
                draining.unlink(missing_ok=True)
                logger.info("Drained %d records from spool", len(records))
                return len(records)
            except Exception:
                logger.exception("Spool drain failed, keeping file")
                return 0
        else:
            draining.unlink(missing_ok=True)
            return 0


spool = SpoolWriter(config.spool.dir)


def _validate_table_and_columns(table_name: str, record: dict) -> None:
    """Raise ValueError if table or any column is not in the whitelist."""
    allowed_cols = ALLOWED_TABLES.get(table_name)
    if allowed_cols is None:
        raise ValueError(f"Unknown table: {table_name!r}")
    invalid = set(record.keys()) - allowed_cols
    if invalid:
        raise ValueError(f"Invalid columns for {table_name!r}: {invalid}")


async def persist(table_name: str, record: dict) -> bool:
    """Write to PG with spool fallback. Returns True if PG succeeded."""
    _validate_table_and_columns(table_name, record)
    try:
        async with async_session() as session:
            from sqlalchemy import text

            cols = ", ".join(record.keys())
            placeholders = ", ".join(f":{k}" for k in record.keys())
            # table_name and cols are whitelist-validated above
            stmt = text(
                f"INSERT INTO sentinel.{table_name} ({cols}) VALUES ({placeholders})"  # noqa: S608
            )
            await session.execute(stmt, record)
            await session.commit()
            return True
    except Exception:
        logger.warning("PG write failed for %s, spooling", table_name)
        spool.append({"_table": table_name, **record})
        return False


async def drain_spool_loop():
    """Background loop to drain spool when PG recovers."""
    while True:
        await asyncio.sleep(config.spool.drain_interval)
        try:

            async def _writer(records):
                async with async_session() as session:
                    from sqlalchemy import text

                    for rec in records:
                        table = rec.pop("_table", "health_checks")
                        rec.pop("_spooled_at", None)
                        try:
                            _validate_table_and_columns(table, rec)
                        except ValueError:
                            logger.warning(
                                "Spool record rejected (invalid table/columns): %s", table
                            )
                            continue
                        cols = ", ".join(rec.keys())
                        placeholders = ", ".join(f":{k}" for k in rec.keys())
                        # table and cols are whitelist-validated above
                        sql = (
                            f"INSERT INTO sentinel.{table}"  # noqa: S608
                            f" ({cols}) VALUES ({placeholders})"
                            " ON CONFLICT DO NOTHING"
                        )
                        stmt = text(sql)
                        await session.execute(stmt, rec)
                    await session.commit()

            await spool.drain(_writer)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: S110
            pass  # PG still down, try again next cycle
