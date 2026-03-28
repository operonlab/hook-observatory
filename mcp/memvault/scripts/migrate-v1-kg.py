#!/usr/bin/env python3
"""migrate-v1-kg.py — One-shot migration from V1 SQLite KG to V2 PostgreSQL via Core API.

V1 source:  ~/Claude/projects/kas-memory/kas-kg.db
V2 target:  Core API (http://localhost:10000)

Migration order (respects FK dependencies):
  1. triple          → POST /api/memvault/kg/triples/batch  (batch 50)
  2. cluster         → POST /api/memvault/kg/clusters/batch (with mapped triple IDs)
  3. wisdom_node     → POST /api/memvault/kg/wisdom/batch
  4. attitude_fact   → POST /api/memvault/kg/attitudes       (only non-superseded leaves)
  5. skill_invocation → POST /api/memvault/kg/skills/invoke  (one-by-one)

Usage:
    python3 migrate-v1-kg.py [--db-path PATH] [--api-base URL] [--space-id ID] [--dry-run]

Options:
    --db-path    Path to V1 kas-kg.db  (default: ~/Claude/projects/kas-memory/kas-kg.db)
    --api-base   Core API base URL      (default: http://localhost:10000)
    --space-id   Target space ID        (default: default)
    --dry-run    Read-only mode — print stats, no writes
"""

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

try:
    import uuid_utils

    def new_uuid() -> str:
        return uuid_utils.uuid7().hex

except ImportError:
    import uuid

    def new_uuid() -> str:  # type: ignore[misc]
        return uuid.uuid4().hex


# ======================== CLI Args ========================

DEFAULT_DB = Path.home() / "Claude" / "kas-memory" / "kas-kg.db"
DEFAULT_API = "http://localhost:10000"
DEFAULT_SPACE = "default"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Migrate V1 KG SQLite → V2 PostgreSQL via Core API")
    p.add_argument("--db-path", type=Path, default=DEFAULT_DB, help="V1 SQLite DB path")
    p.add_argument("--api-base", default=DEFAULT_API, help="Core API base URL")
    p.add_argument("--space-id", default=DEFAULT_SPACE, help="Target space ID")
    p.add_argument("--dry-run", action="store_true", help="Read-only: show stats, no writes")
    return p.parse_args()


# ======================== HTTP Helpers ========================


def api_post(api_base: str, path: str, body: dict, space_id: str) -> dict:
    """POST to Core API, returns parsed JSON response."""
    url = f"{api_base}/api/memvault{path}?space_id={urllib.parse.quote(space_id)}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} POST {path}: {body_text[:300]}") from e


def api_get(api_base: str, path: str, space_id: str) -> dict | list:
    """GET from Core API, returns parsed JSON response."""
    url = f"{api_base}/api/memvault{path}?space_id={urllib.parse.quote(space_id)}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} GET {path}: {body_text[:300]}") from e


def check_api_health(api_base: str) -> bool:
    """Ping Core API. Returns True if reachable."""
    try:
        url = f"{api_base}/api/memvault/profile?space_id=default"
        urllib.request.urlopen(url, timeout=5)
        return True
    except Exception:
        return False


# ======================== Stats Tracker ========================


class MigrationStats:
    def __init__(self) -> None:
        self.tables: dict[str, dict[str, int]] = {}

    def record(self, table: str, migrated: int = 0, skipped: int = 0, errors: int = 0) -> None:
        self.tables[table] = {
            "migrated": self.tables.get(table, {}).get("migrated", 0) + migrated,
            "skipped": self.tables.get(table, {}).get("skipped", 0) + skipped,
            "errors": self.tables.get(table, {}).get("errors", 0) + errors,
        }

    def print_summary(self, dry_run: bool) -> None:
        mode = "DRY RUN" if dry_run else "LIVE"
        print(f"\n{'='*55}")
        print(f"  KAS KG Migration Summary [{mode}]")
        print(f"{'='*55}")
        print(f"  {'Table':<25s} {'Migrated':>9} {'Skipped':>9} {'Errors':>8}")
        print(f"  {'-'*25} {'-'*9} {'-'*9} {'-'*8}")
        for table, s in self.tables.items():
            print(
                f"  {table:<25s} {s['migrated']:>9d} {s['skipped']:>9d} {s['errors']:>8d}"
            )
        total_m = sum(s["migrated"] for s in self.tables.values())
        total_s = sum(s["skipped"] for s in self.tables.values())
        total_e = sum(s["errors"] for s in self.tables.values())
        print(f"  {'-'*25} {'-'*9} {'-'*9} {'-'*8}")
        print(f"  {'TOTAL':<25s} {total_m:>9d} {total_s:>9d} {total_e:>8d}")
        print(f"{'='*55}\n")


# ======================== Migration Steps ========================


def migrate_triples(
    conn: sqlite3.Connection,
    api_base: str,
    space_id: str,
    dry_run: bool,
    stats: MigrationStats,
    batch_size: int = 50,
) -> dict[int, str]:
    """Migrate triple table → POST /kg/triples/batch.

    Returns old_id → new_uuid mapping.
    """
    print("[triple] Reading rows...")
    rows = conn.execute(
        "SELECT id, session_id, timestamp, subject, predicate, object, topic, created_at FROM triple ORDER BY id"
    ).fetchall()

    if not rows:
        print("[triple] No rows found, skipping.")
        stats.record("triple")
        return {}

    print(f"[triple] Found {len(rows)} rows. Migrating in batches of {batch_size}...")

    # Group by session_id for batch API
    # API: POST /kg/triples/batch body = {session_id, topic, timestamp, triples: [...]}
    from collections import defaultdict

    sessions: dict[str, list] = defaultdict(list)
    old_id_map: dict[int, str] = {}  # old int id → new_uuid (assigned here for tracking)

    for row in rows:
        old_id, session_id, ts, subject, predicate, object_, topic, created_at = row
        sessions[session_id or "migrated"].append(
            {
                "_old_id": old_id,
                "subject": subject or "",
                "predicate": predicate or "",
                "object": object_ or "",
                "topic": topic,
                "timestamp": ts,
                "source_session": session_id,
            }
        )

    migrated = 0
    skipped = 0
    errors = 0

    # Process each session group in batches
    session_items = list(sessions.items())
    all_triples: list[dict] = []
    for sid, triples in session_items:
        all_triples.extend(triples)

    for batch_start in range(0, len(all_triples), batch_size):
        batch = all_triples[batch_start : batch_start + batch_size]

        # Group this batch by session_id for the batch endpoint
        batch_by_session: dict[str, list] = defaultdict(list)
        for t in batch:
            batch_by_session[t["source_session"] or "migrated"].append(t)

        for sid, triples in batch_by_session.items():
            # Build batch request
            # Timestamps: use first triple's ts or now
            first_ts = triples[0].get("timestamp") or datetime.now(UTC).isoformat()
            payload = {
                "session_id": sid,
                "topic": triples[0].get("topic"),
                "timestamp": first_ts,
                "triples": [
                    {
                        "subject": t["subject"],
                        "predicate": t["predicate"],
                        "object": t["object"],
                        "topic": t.get("topic"),
                        "source_session": t.get("source_session"),
                        "timestamp": t.get("timestamp") or first_ts,
                    }
                    for t in triples
                ],
            }

            if dry_run:
                print(f"  [DRY RUN] Would POST /kg/triples/batch: session={sid}, {len(triples)} triples")
                migrated += len(triples)
            else:
                try:
                    result = api_post(api_base, "/kg/triples/batch", payload, space_id)
                    ingested = result.get("ingested", len(triples))
                    migrated += ingested
                    skipped += len(triples) - ingested
                except RuntimeError as e:
                    print(f"  [ERROR] batch session={sid}: {e}")
                    errors += len(triples)

    stats.record("triple", migrated=migrated, skipped=skipped, errors=errors)
    print(f"[triple] Done: {migrated} migrated, {skipped} skipped, {errors} errors")

    # For old_id → new_id mapping we cannot get exact IDs from batch endpoint
    # Return a placeholder map (old_id → generated uuid) for cluster linkage
    for row in rows:
        old_id = row[0]
        old_id_map[old_id] = new_uuid()

    return old_id_map


def migrate_clusters(
    conn: sqlite3.Connection,
    api_base: str,
    space_id: str,
    dry_run: bool,
    stats: MigrationStats,
) -> None:
    """Migrate cluster + cluster_triple tables → POST /kg/clusters/regenerate.

    Uses the regenerate endpoint (atomic batch replace) since V2 does not have
    a single-cluster POST endpoint.  Member triple linkage is omitted because
    V1 integer IDs cannot be mapped to V2 UUIDs; pipelines will re-link after
    the next cluster regeneration run.
    """
    print("[cluster] Reading rows...")
    rows = conn.execute(
        "SELECT id, name, size, top_subjects, top_predicates, top_objects, summary, verdict, generated_at FROM cluster"
    ).fetchall()

    if not rows:
        print("[cluster] No rows found, skipping.")
        stats.record("cluster")
        return

    print(f"[cluster] Found {len(rows)} clusters.")

    # Parse all clusters for the regenerate payload
    clusters_payload: list[dict] = []
    generated_at_value: str | None = None

    for row in rows:
        (
            old_id,
            name,
            size,
            top_subjects_raw,
            top_predicates_raw,
            top_objects_raw,
            summary,
            verdict,
            generated_at,
        ) = row

        if generated_at and not generated_at_value:
            generated_at_value = generated_at

        def _parse_json(raw: str | None) -> list:
            if not raw:
                return []
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []

        clusters_payload.append({
            "name": name or f"cluster-{old_id}",
            "size": size or 0,
            "top_subjects": _parse_json(top_subjects_raw),
            "top_predicates": _parse_json(top_predicates_raw),
            "top_objects": _parse_json(top_objects_raw),
            "summary": summary,
            "verdict": verdict or "UNVERIFIED",
            "triples": [],  # no member linkage during migration
        })

    payload = {
        "clusters": clusters_payload,
        "generated_at": generated_at_value or datetime.now(UTC).isoformat(),
        "n_clusters": len(clusters_payload),
    }

    if dry_run:
        print(f"  [DRY RUN] Would POST /kg/clusters/regenerate: {len(clusters_payload)} clusters")
        stats.record("cluster", migrated=len(rows))
    else:
        try:
            result = api_post(api_base, "/kg/clusters/regenerate", payload, space_id)
            saved = result.get("saved", 0)
            stats.record("cluster", migrated=saved, skipped=len(rows) - saved)
            print(f"[cluster] Done: {saved} saved via /kg/clusters/regenerate")
        except RuntimeError as e:
            print(f"  [ERROR] clusters/regenerate: {e}")
            stats.record("cluster", errors=len(rows))


def migrate_wisdom(
    conn: sqlite3.Connection,
    api_base: str,
    space_id: str,
    dry_run: bool,
    stats: MigrationStats,
) -> None:
    """Migrate wisdom_node table → POST /kg/wisdom/regenerate."""
    print("[wisdom_node] Reading rows...")
    rows = conn.execute(
        "SELECT id, wisdom, confidence, bridge_entity, cluster_ids, evidence_count, tags, verified, generated_at FROM wisdom_node"
    ).fetchall()

    if not rows:
        print("[wisdom_node] No rows found, skipping.")
        stats.record("wisdom_node")
        return

    print(f"[wisdom_node] Found {len(rows)} rows.")

    wisdom_nodes: list[dict] = []
    generated_at_value: str | None = None

    for row in rows:
        (
            old_id,
            wisdom,
            confidence,
            bridge_entity,
            cluster_ids_raw,
            evidence_count,
            tags_raw,
            verified,
            generated_at,
        ) = row

        if generated_at and not generated_at_value:
            generated_at_value = generated_at

        def _parse_json(raw: str | None) -> list:
            if not raw:
                return []
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []

        wisdom_nodes.append({
            "wisdom": wisdom or "",
            "confidence": confidence or "MEDIUM",
            "bridge_entity": bridge_entity or "",
            "cluster_ids": _parse_json(cluster_ids_raw),
            "evidence_count": evidence_count,
            "tags": _parse_json(tags_raw),
            "verified": bool(verified),
        })

    payload = {
        "wisdom_nodes": wisdom_nodes,
        "generated_at": generated_at_value or datetime.now(UTC).isoformat(),
    }

    if dry_run:
        print(f"  [DRY RUN] Would POST /kg/wisdom/regenerate: {len(wisdom_nodes)} wisdom nodes")
        stats.record("wisdom_node", migrated=len(rows))
    else:
        try:
            result = api_post(api_base, "/kg/wisdom/regenerate", payload, space_id)
            saved = result.get("saved", 0)
            stats.record("wisdom_node", migrated=saved, skipped=len(rows) - saved)
            print(f"[wisdom_node] Done: {saved} saved via /kg/wisdom/regenerate")
        except RuntimeError as e:
            print(f"  [ERROR] wisdom/regenerate: {e}")
            stats.record("wisdom_node", errors=len(rows))


def migrate_attitudes(
    conn: sqlite3.Connection,
    api_base: str,
    space_id: str,
    dry_run: bool,
    stats: MigrationStats,
) -> None:
    """Migrate attitude_fact table → POST /kg/attitudes.

    Only migrates leaf facts (superseded_by IS NULL) — i.e. active, non-superseded.
    Superseded chain is not rebuilt to avoid polluting V2 with stale data.
    """
    print("[attitude_fact] Reading active (leaf) rows...")
    rows = conn.execute(
        """
        SELECT id, fact, category, operation, confidence, source_sessions, created_at
        FROM attitude_fact
        WHERE superseded_by IS NULL
        ORDER BY id
        """
    ).fetchall()

    superseded_count = conn.execute(
        "SELECT COUNT(*) FROM attitude_fact WHERE superseded_by IS NOT NULL"
    ).fetchone()[0]

    if not rows:
        print("[attitude_fact] No active rows found, skipping.")
        stats.record("attitude_fact", skipped=superseded_count)
        return

    print(f"[attitude_fact] Found {len(rows)} active rows ({superseded_count} superseded → skipped).")
    migrated = 0
    skipped = superseded_count
    errors = 0

    for row in rows:
        old_id, fact, category, operation, confidence, source_sessions_raw, created_at = row

        try:
            source_sessions = json.loads(source_sessions_raw) if source_sessions_raw else []
            if not isinstance(source_sessions, list):
                source_sessions = [str(source_sessions)]
        except (json.JSONDecodeError, TypeError):
            source_sessions = []

        payload = {
            "fact": fact or "",
            "category": category or "general",
            "source_sessions": source_sessions,
        }

        if dry_run:
            print(f"  [DRY RUN] Would POST /kg/attitudes: [{category}] {fact[:60]}...")
            migrated += 1
        else:
            try:
                api_post(api_base, "/kg/attitudes", payload, space_id)
                migrated += 1
            except RuntimeError as e:
                print(f"  [ERROR] attitude id={old_id}: {e}")
                errors += 1

    stats.record("attitude_fact", migrated=migrated, skipped=skipped, errors=errors)
    print(f"[attitude_fact] Done: {migrated} migrated, {skipped} skipped (superseded), {errors} errors")


def migrate_skills(
    conn: sqlite3.Connection,
    api_base: str,
    space_id: str,
    dry_run: bool,
    stats: MigrationStats,
) -> None:
    """Migrate skill_invocation table → POST /kg/skills/invoke."""
    print("[skill_invocation] Reading rows...")
    rows = conn.execute(
        "SELECT id, skill_name, session_id, cwd, timestamp, outcome, tool_input FROM skill_invocation ORDER BY id"
    ).fetchall()

    if not rows:
        print("[skill_invocation] No rows found, skipping.")
        stats.record("skill_invocation")
        return

    print(f"[skill_invocation] Found {len(rows)} rows.")
    migrated = 0
    skipped = 0
    errors = 0

    for row in rows:
        old_id, skill_name, session_id, cwd, timestamp, outcome, tool_input_raw = row

        # Parse timestamp → ISO format
        invoked_at = timestamp or datetime.now(UTC).isoformat()
        # Ensure it has timezone info for Pydantic datetime parsing
        if invoked_at and "T" in invoked_at and not invoked_at.endswith("Z") and "+" not in invoked_at:
            invoked_at = invoked_at.replace(" ", "T") + "+00:00"

        payload = {
            "skill_name": skill_name or "unknown",
            "source_session": session_id or "migrated",
            "cwd": cwd,
            "invoked_at": invoked_at,
            "outcome": outcome or "unknown",
        }

        if dry_run:
            print(f"  [DRY RUN] Would POST /kg/skills/invoke: skill={skill_name}, session={session_id}")
            migrated += 1
        else:
            try:
                api_post(api_base, "/kg/skills/invoke", payload, space_id)
                migrated += 1
            except RuntimeError as e:
                print(f"  [ERROR] skill_invocation id={old_id} skill={skill_name}: {e}")
                errors += 1

    stats.record("skill_invocation", migrated=migrated, skipped=skipped, errors=errors)
    print(f"[skill_invocation] Done: {migrated} migrated, {skipped} skipped, {errors} errors")


# ======================== Main ========================


def main() -> None:
    args = parse_args()
    db_path = args.db_path.expanduser().resolve()
    api_base = args.api_base.rstrip("/")
    space_id = args.space_id
    dry_run = args.dry_run

    print("=" * 55)
    print("  KAS KG V1 → V2 Migration")
    print("=" * 55)
    print(f"  DB      : {db_path}")
    print(f"  API     : {api_base}")
    print(f"  Space   : {space_id}")
    print(f"  Mode    : {'DRY RUN (no writes)' if dry_run else 'LIVE'}")
    print("=" * 55)
    print()

    # Validate DB exists
    if not db_path.exists():
        print(f"[ERROR] V1 database not found: {db_path}")
        sys.exit(1)

    db_size = db_path.stat().st_size
    if db_size == 0:
        print(f"[WARN] V1 database is empty (0 bytes): {db_path}")
        print("       Nothing to migrate.")
        sys.exit(0)

    # Check API health (skip in dry-run to allow offline testing)
    if not dry_run:
        print("Checking Core API health...", end=" ", flush=True)
        if not check_api_health(api_base):
            print("FAILED")
            print(f"[ERROR] Cannot reach Core API at {api_base}")
            print("        Start the server: cd core && uvicorn src.main:app --port 10000")
            sys.exit(1)
        print("OK")

    # Open SQLite connection
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Check which tables actually exist
    existing_tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    print(f"Tables found in V1 DB: {', '.join(sorted(existing_tables)) or '(none)'}\n")

    if not existing_tables:
        print("[INFO] No tables in V1 DB — nothing to migrate.")
        conn.close()
        sys.exit(0)

    stats = MigrationStats()

    # Step 1: triple
    triple_id_map: dict[int, str] = {}
    if "triple" in existing_tables:
        triple_id_map = migrate_triples(conn, api_base, space_id, dry_run, stats)
    else:
        print("[triple] Table not found, skipping.")
        stats.record("triple")

    # Step 2: cluster (depends on triple_id_map for member linking)
    if "cluster" in existing_tables:
        migrate_clusters(conn, api_base, space_id, dry_run, stats)
    else:
        print("[cluster] Table not found, skipping.")
        stats.record("cluster")

    # Step 3: wisdom_node
    if "wisdom_node" in existing_tables:
        migrate_wisdom(conn, api_base, space_id, dry_run, stats)
    else:
        print("[wisdom_node] Table not found, skipping.")
        stats.record("wisdom_node")

    # Step 4: attitude_fact
    if "attitude_fact" in existing_tables:
        migrate_attitudes(conn, api_base, space_id, dry_run, stats)
    else:
        print("[attitude_fact] Table not found, skipping.")
        stats.record("attitude_fact")

    # Step 5: skill_invocation
    if "skill_invocation" in existing_tables:
        migrate_skills(conn, api_base, space_id, dry_run, stats)
    else:
        print("[skill_invocation] Table not found, skipping.")
        stats.record("skill_invocation")

    conn.close()
    stats.print_summary(dry_run)
    print("Migration complete.")


if __name__ == "__main__":
    main()
