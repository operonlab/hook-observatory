"""Task manager — Multi-agent pipeline coordination via PostgreSQL.

Modes:
  linear  – Sequential stages, auto-advancement on completion.
  dag     – Dependency graph, parallel dispatch when deps resolve.
  debate  – N agents examine same question, cross-review, synthesize.

Storage: asyncpg → agentops.projects (JSONB state column).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg

VALID_STATUSES = ("pending", "in-progress", "done", "failed", "skipped")


# ── Helpers ───────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gen_id() -> str:
    return str(uuid4())[:8]


# ── Persistence ───────────────────────────────────────────────────


async def load_project(pool: asyncpg.Pool, name: str) -> dict:
    row = await pool.fetchrow("SELECT state FROM projects WHERE name = $1", name)
    if row is None:
        raise FileNotFoundError(f"Project '{name}' not found")
    state = row["state"]
    return json.loads(state) if isinstance(state, str) else state


async def save_project(pool: asyncpg.Pool, name: str, data: dict) -> None:
    state_json = json.dumps(data, ensure_ascii=False)
    now = datetime.now(UTC)
    # Parse created_at string to datetime if present, else use now
    created_at_str = data.get("created_at", "")
    try:
        created_at = datetime.fromisoformat(created_at_str) if created_at_str else now
    except (ValueError, TypeError):
        created_at = now
    await pool.execute(
        """
        INSERT INTO projects (id, name, mode, goal, workspace, status, created_at, updated_at, state)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (name) DO UPDATE SET
            updated_at = EXCLUDED.updated_at,
            state = EXCLUDED.state,
            status = EXCLUDED.status
        """,
        data.get("id", _gen_id()),
        name,
        data.get("mode", ""),
        data.get("goal", ""),
        data.get("workspace", ""),
        data.get("status", "active"),
        created_at,
        now,
        state_json,
    )


async def list_projects(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        "SELECT name, mode, goal, status FROM projects ORDER BY created_at DESC"
    )
    return [dict(r) for r in rows]


# ── Data constructors ─────────────────────────────────────────────


def make_stage(stage_id: str, *, desc: str = "", agent: str = "") -> dict:
    return {
        "id": stage_id,
        "agent": agent or stage_id,
        "description": desc,
        "status": "pending",
        "result": "",
        "assigned_at": "",
        "completed_at": "",
    }


def make_task(
    task_id: str,
    *,
    agent: str = "",
    desc: str = "",
    deps: list[str] | None = None,
) -> dict:
    return {
        "id": task_id,
        "agent": agent or task_id,
        "description": desc,
        "dependencies": deps or [],
        "status": "pending",
        "result": "",
        "assigned_at": "",
        "completed_at": "",
    }


# ── DAG helpers ───────────────────────────────────────────────────


def compute_ready_tasks(proj: dict) -> list[dict]:
    tasks = proj.get("tasks", [])
    done_ids = {t["id"] for t in tasks if t["status"] == "done"}
    return [
        t
        for t in tasks
        if t["status"] == "pending" and all(d in done_ids for d in t.get("dependencies", []))
    ]


def detect_cycles(proj: dict) -> list[str]:
    tasks_map = {t["id"]: t.get("dependencies", []) for t in proj.get("tasks", [])}
    visited: set[str] = set()
    stack: set[str] = set()
    cycles: list[str] = []

    def dfs(node: str) -> bool:
        visited.add(node)
        stack.add(node)
        for dep in tasks_map.get(node, []):
            if dep not in visited:
                if dfs(dep):
                    return True
            elif dep in stack:
                cycles.append(f"{node} -> {dep}")
                return True
        stack.discard(node)
        return False

    for tid in tasks_map:
        if tid not in visited:
            dfs(tid)
    return cycles


# ── Operations ────────────────────────────────────────────────────


async def init_project(
    pool: asyncpg.Pool,
    name: str,
    mode: str,
    *,
    goal: str = "",
    pipeline: str = "",
    workspace: str = "",
    force: bool = False,
) -> dict:
    if not force:
        try:
            await load_project(pool, name)
            raise FileExistsError(f"Project '{name}' already exists")
        except FileNotFoundError:
            pass

    proj: dict = {
        "id": _gen_id(),
        "name": name,
        "mode": mode,
        "goal": goal,
        "status": "active",
        "created_at": _now(),
        "workspace": workspace,
    }

    if mode == "linear":
        stages = [s.strip() for s in pipeline.split(",") if s.strip()]
        if not stages:
            raise ValueError("Linear mode requires pipeline stages (comma-separated)")
        proj["stages"] = [make_stage(s) for s in stages]
        proj["current_stage"] = 0
    elif mode == "dag":
        proj["tasks"] = []
    elif mode == "debate":
        proj["debaters"] = []
        proj["rounds"] = []
        proj["question"] = goal
    else:
        raise ValueError(f"Unknown mode: {mode}")

    await save_project(pool, name, proj)
    return proj


async def add_task(
    pool: asyncpg.Pool,
    project_name: str,
    task_id: str,
    *,
    agent: str = "",
    desc: str = "",
    deps: str = "",
) -> dict:
    proj = await load_project(pool, project_name)
    if proj["mode"] != "dag":
        raise ValueError("'add' is for DAG mode only")

    dep_list = [d.strip() for d in deps.split(",") if d.strip()]
    task = make_task(task_id, agent=agent, desc=desc, deps=dep_list)
    proj.setdefault("tasks", []).append(task)

    cycles = detect_cycles(proj)
    if cycles:
        raise ValueError(f"Cycle detected: {cycles}")

    await save_project(pool, project_name, proj)
    return task


async def add_debater(
    pool: asyncpg.Pool,
    project_name: str,
    debater_id: str,
    *,
    agent: str = "",
    perspective: str = "",
) -> dict:
    proj = await load_project(pool, project_name)
    if proj["mode"] != "debate":
        raise ValueError("'add-debater' is for debate mode only")

    debater = {
        "id": debater_id,
        "agent": agent or debater_id,
        "perspective": perspective,
        "added_at": _now(),
    }
    proj.setdefault("debaters", []).append(debater)
    await save_project(pool, project_name, proj)
    return debater


async def get_status(pool: asyncpg.Pool, project_name: str) -> dict:
    return await load_project(pool, project_name)


async def get_next_stage(pool: asyncpg.Pool, project_name: str) -> dict | None:
    proj = await load_project(pool, project_name)
    if proj["mode"] != "linear":
        raise ValueError("'next' is for linear mode only")
    stages = proj.get("stages", [])
    current = proj.get("current_stage", 0)
    if current >= len(stages):
        return None
    return stages[current]


async def get_ready_tasks(pool: asyncpg.Pool, project_name: str) -> list[dict]:
    proj = await load_project(pool, project_name)
    if proj["mode"] != "dag":
        raise ValueError("'ready' is for DAG mode only")
    return compute_ready_tasks(proj)


async def update_task_status(
    pool: asyncpg.Pool,
    project_name: str,
    task_id: str,
    status: str,
) -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    proj = await load_project(pool, project_name)
    mode = proj["mode"]
    result = {"task_id": task_id, "status": status, "newly_ready": []}

    if mode == "linear":
        for i, s in enumerate(proj.get("stages", [])):
            if s["id"] == task_id:
                s["status"] = status
                if status == "in-progress":
                    s["assigned_at"] = _now()
                elif status in ("done", "failed", "skipped"):
                    s["completed_at"] = _now()
                    if status == "done" and i == proj.get("current_stage", 0):
                        proj["current_stage"] = i + 1
                        stages = proj.get("stages", [])
                        if i + 1 < len(stages):
                            result["next_stage"] = stages[i + 1]["id"]
                break
        else:
            raise ValueError(f"Stage '{task_id}' not found")
    elif mode == "dag":
        for t in proj.get("tasks", []):
            if t["id"] == task_id:
                t["status"] = status
                if status == "in-progress":
                    t["assigned_at"] = _now()
                elif status in ("done", "failed", "skipped"):
                    t["completed_at"] = _now()
                break
        else:
            raise ValueError(f"Task '{task_id}' not found")

        if status == "done":
            result["newly_ready"] = [t["id"] for t in compute_ready_tasks(proj)]
    else:
        raise ValueError(f"Update not supported in '{mode}' mode")

    await save_project(pool, project_name, proj)
    return result


async def record_result(
    pool: asyncpg.Pool,
    project_name: str,
    task_id: str,
    text: str,
) -> None:
    proj = await load_project(pool, project_name)
    mode = proj["mode"]
    items = proj.get("stages" if mode == "linear" else "tasks", [])

    for item in items:
        if item["id"] == task_id:
            item["result"] = text
            if item["status"] == "pending":
                item["status"] = "in-progress"
                item["assigned_at"] = _now()
            break
    else:
        raise ValueError(f"'{task_id}' not found")

    await save_project(pool, project_name, proj)


async def manage_round(
    pool: asyncpg.Pool,
    project_name: str,
    action: str,
    *,
    debater_id: str = "",
    text: str = "",
) -> dict:
    proj = await load_project(pool, project_name)
    if proj["mode"] != "debate":
        raise ValueError("'round' is for debate mode only")

    rounds = proj.setdefault("rounds", [])
    debaters = proj.get("debaters", [])
    result: dict = {"action": action}

    if action == "start":
        new_round = {
            "round_number": len(rounds) + 1,
            "phase": "initial",
            "started_at": _now(),
            "responses": [],
        }
        rounds.append(new_round)
        result["round_number"] = new_round["round_number"]
        result["debater_count"] = len(debaters)
    elif action == "submit":
        if not rounds:
            raise ValueError("No active round")
        current_round = rounds[-1]
        response = {
            "debater_id": debater_id,
            "content": text,
            "submitted_at": _now(),
            "phase": current_round["phase"],
        }
        current_round.setdefault("responses", []).append(response)
        result["round_number"] = current_round["round_number"]
    elif action == "cross-review":
        if not rounds:
            raise ValueError("No round data")
        rounds[-1]["phase"] = "cross-review"
        result["phase"] = "cross-review"
    elif action == "synthesize":
        if not rounds:
            raise ValueError("No round data")
        rounds[-1]["phase"] = "synthesis"
        result["phase"] = "synthesis"
    elif action == "status":
        if not rounds:
            return {"action": "status", "rounds": 0}
        current_round = rounds[-1]
        responses = current_round.get("responses", [])
        responded = {r["debater_id"] for r in responses if r["phase"] == current_round["phase"]}
        result["round_number"] = current_round["round_number"]
        result["phase"] = current_round["phase"]
        result["responded"] = list(responded)
        result["pending"] = [d["id"] for d in debaters if d["id"] not in responded]
    else:
        raise ValueError(f"Unknown round action: {action}")

    await save_project(pool, project_name, proj)
    return result


async def reset_project(pool: asyncpg.Pool, project_name: str) -> None:
    proj = await load_project(pool, project_name)
    mode = proj["mode"]

    if mode == "linear":
        for s in proj.get("stages", []):
            s["status"] = "pending"
            s["result"] = ""
            s["assigned_at"] = ""
            s["completed_at"] = ""
        proj["current_stage"] = 0
    elif mode == "dag":
        for t in proj.get("tasks", []):
            t["status"] = "pending"
            t["result"] = ""
            t["assigned_at"] = ""
            t["completed_at"] = ""
    elif mode == "debate":
        proj["rounds"] = []

    await save_project(pool, project_name, proj)
