import os
import subprocess

import pytest
import requests

CORE_URL = "http://localhost:10000"
SPACE_ID = "default"
ACTIVE_COUNT_SQL = (
    "SELECT COUNT(*) FROM memvault.blocks "
    "WHERE space_id='default' AND deleted_at IS NULL AND invalid_at IS NULL;"
)


def _internal_key():
    k = os.environ.get("CORE_INTERNAL_API_KEY")
    if not k:
        pytest.skip("CORE_INTERNAL_API_KEY not set")
    return k


def _psql(sql: str) -> str:
    r = subprocess.run(
        [
            "docker",
            "exec",
            "ws-infra-postgres-1",
            "psql",
            "-U",
            "joneshong",
            "-d",
            "workshop",
            "-t",
            "-A",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if r.returncode != 0:
        pytest.fail(f"psql failed: {r.stderr}")
    return r.stdout.strip()


def _dream_dry_run() -> dict:
    r = requests.post(
        f"{CORE_URL}/api/memvault/dream",
        params={"space_id": SPACE_ID, "dry_run": "true", "force": "true"},
        headers={"X-Internal-Key": _internal_key()},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def test_total_blocks_matches_active_filter_count():
    sql_count = int(_psql(ACTIVE_COUNT_SQL))
    resp = _dream_dry_run()
    total = resp["phase_orient"]["total_blocks"]
    assert total == sql_count, (
        f"dream total_blocks={total} but SQL active count={sql_count} "
        f"(filter: deleted_at IS NULL AND invalid_at IS NULL)"
    )


def test_total_blocks_equals_sum_of_block_stats():
    resp = _dream_dry_run()
    po = resp["phase_orient"]
    total = po["total_blocks"]
    stats_sum = sum(po["block_stats"].values())
    assert total == stats_sum, (
        f"total_blocks={total} != sum(block_stats)={stats_sum} stats={po['block_stats']}"
    )


def test_soft_deleted_excluded():
    block_id = _psql(
        "SELECT id FROM memvault.blocks "
        "WHERE space_id='default' AND deleted_at IS NULL AND invalid_at IS NULL "
        "LIMIT 1;"
    )
    if not block_id:
        pytest.skip("no active blocks in default space")

    baseline = _dream_dry_run()["phase_orient"]["total_blocks"]
    baseline_sql = int(_psql(ACTIVE_COUNT_SQL))
    assert baseline == baseline_sql, "precondition: invariant must hold before mutation"

    _psql(f"UPDATE memvault.blocks SET deleted_at = NOW() WHERE id='{block_id}';")
    try:
        mutated = _dream_dry_run()["phase_orient"]["total_blocks"]
        mutated_sql = int(_psql(ACTIVE_COUNT_SQL))
        assert mutated == baseline - 1, f"after soft-delete expected {baseline - 1}, got {mutated}"
        assert mutated == mutated_sql, (
            f"post-mutation invariant broken: dream={mutated} sql={mutated_sql}"
        )
    finally:
        _psql(f"UPDATE memvault.blocks SET deleted_at = NULL WHERE id='{block_id}';")

    restored = int(_psql(ACTIVE_COUNT_SQL))
    assert restored == baseline_sql, (
        f"ROLLBACK FAILED: expected {baseline_sql}, got {restored}, "
        f"block_id={block_id} still soft-deleted"
    )
