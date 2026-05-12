//! Task manager — port of `agent_metrics.engines.task_manager`.
//!
//! Linear / DAG / debate project state machine, persisted in SQLite
//! `projects` table (state JSON).

use anyhow::Result;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sqlx::SqlitePool;
use std::collections::{BTreeSet, HashMap, HashSet};
use uuid::Uuid;

pub const VALID_STATUSES: &[&str] = &["pending", "in-progress", "done", "failed", "skipped"];

fn now_iso() -> String {
    Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

fn gen_id() -> String {
    let s = Uuid::new_v4().simple().to_string();
    s[..8].to_string()
}

#[derive(Debug, thiserror::Error)]
pub enum TaskError {
    #[error("project '{0}' not found")]
    NotFound(String),
    #[error("project '{0}' already exists")]
    Exists(String),
    #[error("{0}")]
    Validation(String),
}

// ── Persistence ─────────────────────────────────────────────────

pub async fn load_project(pool: &SqlitePool, name: &str) -> Result<Value, TaskError> {
    let row: Option<(String,)> = sqlx::query_as("SELECT state FROM projects WHERE name = ?1")
        .bind(name)
        .fetch_optional(pool)
        .await
        .map_err(|e| TaskError::Validation(e.to_string()))?;
    let row = row.ok_or_else(|| TaskError::NotFound(name.to_string()))?;
    serde_json::from_str(&row.0).map_err(|e| TaskError::Validation(e.to_string()))
}

pub async fn save_project(pool: &SqlitePool, name: &str, data: &Value) -> Result<(), TaskError> {
    let id = data.get("id").and_then(|v| v.as_str()).map(String::from).unwrap_or_else(gen_id);
    let mode = data.get("mode").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let goal = data.get("goal").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let workspace = data.get("workspace").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let status = data.get("status").and_then(|v| v.as_str()).unwrap_or("active").to_string();
    let created_at = data.get("created_at").and_then(|v| v.as_str()).map(String::from)
        .unwrap_or_else(|| Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false));
    let now = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false);
    let state_json = serde_json::to_string(data).map_err(|e| TaskError::Validation(e.to_string()))?;

    sqlx::query(
        "INSERT INTO projects (id, name, mode, goal, workspace, status, created_at, updated_at, state) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9) \
         ON CONFLICT(name) DO UPDATE SET \
            updated_at = excluded.updated_at, \
            state = excluded.state, \
            status = excluded.status",
    )
    .bind(id)
    .bind(name)
    .bind(mode)
    .bind(goal)
    .bind(workspace)
    .bind(status)
    .bind(created_at)
    .bind(now)
    .bind(state_json)
    .execute(pool)
    .await
    .map_err(|e| TaskError::Validation(e.to_string()))?;
    Ok(())
}

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct ProjectSummary {
    pub name: String,
    pub mode: String,
    pub goal: Option<String>,
    pub status: String,
}

pub async fn list_projects(pool: &SqlitePool) -> Result<Vec<ProjectSummary>> {
    let rows = sqlx::query_as::<_, ProjectSummary>(
        "SELECT name, mode, goal, status FROM projects ORDER BY created_at DESC",
    )
    .fetch_all(pool)
    .await?;
    Ok(rows)
}

// ── Constructors ────────────────────────────────────────────────

fn make_stage(stage_id: &str) -> Value {
    json!({
        "id": stage_id,
        "agent": stage_id,
        "description": "",
        "status": "pending",
        "result": "",
        "assigned_at": "",
        "completed_at": ""
    })
}

fn make_task(task_id: &str, agent: &str, desc: &str, deps: Vec<String>) -> Value {
    json!({
        "id": task_id,
        "agent": if agent.is_empty() { task_id } else { agent },
        "description": desc,
        "dependencies": deps,
        "status": "pending",
        "result": "",
        "assigned_at": "",
        "completed_at": ""
    })
}

// ── DAG helpers ─────────────────────────────────────────────────

pub fn compute_ready_tasks(proj: &Value) -> Vec<Value> {
    let tasks: Vec<Value> = proj
        .get("tasks")
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default();
    let done_ids: HashSet<String> = tasks
        .iter()
        .filter(|t| t.get("status").and_then(|s| s.as_str()) == Some("done"))
        .filter_map(|t| t.get("id").and_then(|v| v.as_str()).map(String::from))
        .collect();
    tasks
        .into_iter()
        .filter(|t| {
            if t.get("status").and_then(|s| s.as_str()) != Some("pending") {
                return false;
            }
            t.get("dependencies")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|x| x.as_str())
                        .all(|d| done_ids.contains(d))
                })
                .unwrap_or(true)
        })
        .collect()
}

pub fn detect_cycles(proj: &Value) -> Vec<String> {
    let tasks_map: HashMap<String, Vec<String>> = proj
        .get("tasks")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|t| {
                    let id = t.get("id").and_then(|v| v.as_str())?.to_string();
                    let deps = t
                        .get("dependencies")
                        .and_then(|v| v.as_array())
                        .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
                        .unwrap_or_default();
                    Some((id, deps))
                })
                .collect()
        })
        .unwrap_or_default();

    let mut visited: HashSet<String> = HashSet::new();
    let mut stack: HashSet<String> = HashSet::new();
    let mut cycles: Vec<String> = Vec::new();

    fn dfs(
        node: &str,
        tasks_map: &HashMap<String, Vec<String>>,
        visited: &mut HashSet<String>,
        stack: &mut HashSet<String>,
        cycles: &mut Vec<String>,
    ) -> bool {
        visited.insert(node.into());
        stack.insert(node.into());
        if let Some(deps) = tasks_map.get(node) {
            for dep in deps {
                if !visited.contains(dep) {
                    if dfs(dep, tasks_map, visited, stack, cycles) {
                        return true;
                    }
                } else if stack.contains(dep) {
                    cycles.push(format!("{node} -> {dep}"));
                    return true;
                }
            }
        }
        stack.remove(node);
        false
    }

    let ids: BTreeSet<String> = tasks_map.keys().cloned().collect();
    for tid in ids {
        if !visited.contains(&tid) {
            dfs(&tid, &tasks_map, &mut visited, &mut stack, &mut cycles);
        }
    }
    cycles
}

// ── Operations ──────────────────────────────────────────────────

pub async fn init_project(
    pool: &SqlitePool,
    name: &str,
    mode: &str,
    goal: &str,
    pipeline: &str,
    workspace: &str,
    force: bool,
) -> Result<Value, TaskError> {
    if !force {
        match load_project(pool, name).await {
            Ok(_) => return Err(TaskError::Exists(name.to_string())),
            Err(TaskError::NotFound(_)) => {}
            Err(e) => return Err(e),
        }
    }

    let mut proj = json!({
        "id": gen_id(),
        "name": name,
        "mode": mode,
        "goal": goal,
        "status": "active",
        "created_at": now_iso(),
        "workspace": workspace,
    });

    match mode {
        "linear" => {
            let stages: Vec<Value> = pipeline
                .split(',')
                .map(|s| s.trim())
                .filter(|s| !s.is_empty())
                .map(make_stage)
                .collect();
            if stages.is_empty() {
                return Err(TaskError::Validation(
                    "Linear mode requires pipeline stages (comma-separated)".into(),
                ));
            }
            proj["stages"] = Value::Array(stages);
            proj["current_stage"] = json!(0);
        }
        "dag" => {
            proj["tasks"] = Value::Array(vec![]);
        }
        "debate" => {
            proj["debaters"] = Value::Array(vec![]);
            proj["rounds"] = Value::Array(vec![]);
            proj["question"] = Value::String(goal.to_string());
        }
        other => return Err(TaskError::Validation(format!("Unknown mode: {other}"))),
    }

    save_project(pool, name, &proj).await?;
    Ok(proj)
}

pub async fn add_task(
    pool: &SqlitePool,
    project_name: &str,
    task_id: &str,
    agent: &str,
    desc: &str,
    deps: &str,
) -> Result<Value, TaskError> {
    let mut proj = load_project(pool, project_name).await?;
    if proj.get("mode").and_then(|v| v.as_str()) != Some("dag") {
        return Err(TaskError::Validation("'add' is for DAG mode only".into()));
    }
    let dep_list: Vec<String> = deps.split(',').map(|s| s.trim()).filter(|s| !s.is_empty()).map(String::from).collect();
    let task = make_task(task_id, agent, desc, dep_list);
    proj["tasks"]
        .as_array_mut()
        .ok_or_else(|| TaskError::Validation("invalid tasks array".into()))?
        .push(task.clone());
    let cycles = detect_cycles(&proj);
    if !cycles.is_empty() {
        return Err(TaskError::Validation(format!("Cycle detected: {:?}", cycles)));
    }
    save_project(pool, project_name, &proj).await?;
    Ok(task)
}

pub async fn add_debater(
    pool: &SqlitePool,
    project_name: &str,
    debater_id: &str,
    agent: &str,
    perspective: &str,
) -> Result<Value, TaskError> {
    let mut proj = load_project(pool, project_name).await?;
    if proj.get("mode").and_then(|v| v.as_str()) != Some("debate") {
        return Err(TaskError::Validation("'add-debater' is for debate mode only".into()));
    }
    let debater = json!({
        "id": debater_id,
        "agent": if agent.is_empty() { debater_id } else { agent },
        "perspective": perspective,
        "added_at": now_iso(),
    });
    proj["debaters"]
        .as_array_mut()
        .ok_or_else(|| TaskError::Validation("invalid debaters array".into()))?
        .push(debater.clone());
    save_project(pool, project_name, &proj).await?;
    Ok(debater)
}

pub async fn get_status(pool: &SqlitePool, project_name: &str) -> Result<Value, TaskError> {
    load_project(pool, project_name).await
}

pub async fn get_next_stage(pool: &SqlitePool, project_name: &str) -> Result<Option<Value>, TaskError> {
    let proj = load_project(pool, project_name).await?;
    if proj.get("mode").and_then(|v| v.as_str()) != Some("linear") {
        return Err(TaskError::Validation("'next' is for linear mode only".into()));
    }
    let stages = proj.get("stages").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let current = proj.get("current_stage").and_then(|v| v.as_i64()).unwrap_or(0) as usize;
    Ok(stages.get(current).cloned())
}

pub async fn get_ready_tasks(pool: &SqlitePool, project_name: &str) -> Result<Vec<Value>, TaskError> {
    let proj = load_project(pool, project_name).await?;
    if proj.get("mode").and_then(|v| v.as_str()) != Some("dag") {
        return Err(TaskError::Validation("'ready' is for DAG mode only".into()));
    }
    Ok(compute_ready_tasks(&proj))
}

pub async fn update_task_status(
    pool: &SqlitePool,
    project_name: &str,
    task_id: &str,
    status: &str,
) -> Result<Value, TaskError> {
    if !VALID_STATUSES.contains(&status) {
        return Err(TaskError::Validation(format!("Invalid status: {status}")));
    }
    let mut proj = load_project(pool, project_name).await?;
    let mode = proj.get("mode").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let mut result = json!({
        "task_id": task_id,
        "status": status,
        "newly_ready": [],
    });

    if mode == "linear" {
        let mut found = false;
        let mut next_stage_id: Option<String> = None;
        let stages_owned: Vec<Value> = proj
            .get("stages")
            .and_then(|v| v.as_array().cloned())
            .unwrap_or_default();
        let current = proj.get("current_stage").and_then(|v| v.as_i64()).unwrap_or(0) as usize;

        let mut new_stages = stages_owned.clone();
        for (i, s) in new_stages.iter_mut().enumerate() {
            if s.get("id").and_then(|v| v.as_str()) == Some(task_id) {
                s["status"] = Value::String(status.into());
                if status == "in-progress" {
                    s["assigned_at"] = Value::String(now_iso());
                } else if matches!(status, "done" | "failed" | "skipped") {
                    s["completed_at"] = Value::String(now_iso());
                    if status == "done" && i == current {
                        proj["current_stage"] = json!(i + 1);
                        if let Some(next) = stages_owned.get(i + 1) {
                            if let Some(id) = next.get("id").and_then(|v| v.as_str()) {
                                next_stage_id = Some(id.to_string());
                            }
                        }
                    }
                }
                found = true;
                break;
            }
        }
        if !found {
            return Err(TaskError::Validation(format!("Stage '{task_id}' not found")));
        }
        proj["stages"] = Value::Array(new_stages);
        if let Some(id) = next_stage_id {
            result["next_stage"] = Value::String(id);
        }
    } else if mode == "dag" {
        let mut tasks: Vec<Value> = proj.get("tasks").and_then(|v| v.as_array().cloned()).unwrap_or_default();
        let mut found = false;
        for t in tasks.iter_mut() {
            if t.get("id").and_then(|v| v.as_str()) == Some(task_id) {
                t["status"] = Value::String(status.into());
                if status == "in-progress" {
                    t["assigned_at"] = Value::String(now_iso());
                } else if matches!(status, "done" | "failed" | "skipped") {
                    t["completed_at"] = Value::String(now_iso());
                }
                found = true;
                break;
            }
        }
        if !found {
            return Err(TaskError::Validation(format!("Task '{task_id}' not found")));
        }
        proj["tasks"] = Value::Array(tasks);
        if status == "done" {
            let ids: Vec<Value> = compute_ready_tasks(&proj)
                .into_iter()
                .filter_map(|t| t.get("id").and_then(|v| v.as_str().map(|s| Value::String(s.into()))))
                .collect();
            result["newly_ready"] = Value::Array(ids);
        }
    } else {
        return Err(TaskError::Validation(format!("Update not supported in '{mode}' mode")));
    }

    save_project(pool, project_name, &proj).await?;
    Ok(result)
}

pub async fn record_result(
    pool: &SqlitePool,
    project_name: &str,
    task_id: &str,
    text: &str,
) -> Result<(), TaskError> {
    let mut proj = load_project(pool, project_name).await?;
    let mode = proj.get("mode").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let key = if mode == "linear" { "stages" } else { "tasks" };

    let mut items: Vec<Value> = proj
        .get(key)
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default();
    let mut found = false;
    for item in items.iter_mut() {
        if item.get("id").and_then(|v| v.as_str()) == Some(task_id) {
            item["result"] = Value::String(text.into());
            if item.get("status").and_then(|v| v.as_str()) == Some("pending") {
                item["status"] = Value::String("in-progress".into());
                item["assigned_at"] = Value::String(now_iso());
            }
            found = true;
            break;
        }
    }
    if !found {
        return Err(TaskError::Validation(format!("'{task_id}' not found")));
    }
    proj[key] = Value::Array(items);
    save_project(pool, project_name, &proj).await?;
    Ok(())
}

pub async fn manage_round(
    pool: &SqlitePool,
    project_name: &str,
    action: &str,
    debater_id: &str,
    text: &str,
) -> Result<Value, TaskError> {
    let mut proj = load_project(pool, project_name).await?;
    if proj.get("mode").and_then(|v| v.as_str()) != Some("debate") {
        return Err(TaskError::Validation("'round' is for debate mode only".into()));
    }
    let mut rounds: Vec<Value> = proj.get("rounds").and_then(|v| v.as_array().cloned()).unwrap_or_default();
    let debaters: Vec<Value> = proj.get("debaters").and_then(|v| v.as_array().cloned()).unwrap_or_default();
    let mut result = json!({"action": action});

    match action {
        "start" => {
            let n = rounds.len() + 1;
            let new_round = json!({
                "round_number": n,
                "phase": "initial",
                "started_at": now_iso(),
                "responses": [],
            });
            rounds.push(new_round);
            result["round_number"] = json!(n);
            result["debater_count"] = json!(debaters.len());
        }
        "submit" => {
            if rounds.is_empty() {
                return Err(TaskError::Validation("No active round".into()));
            }
            let last_idx = rounds.len() - 1;
            let phase = rounds[last_idx]
                .get("phase")
                .and_then(|v| v.as_str())
                .unwrap_or("initial")
                .to_string();
            let response = json!({
                "debater_id": debater_id,
                "content": text,
                "submitted_at": now_iso(),
                "phase": phase,
            });
            rounds[last_idx]["responses"]
                .as_array_mut()
                .ok_or_else(|| TaskError::Validation("invalid responses".into()))?
                .push(response);
            result["round_number"] = rounds[last_idx]
                .get("round_number")
                .cloned()
                .unwrap_or(Value::Null);
        }
        "cross-review" => {
            if rounds.is_empty() {
                return Err(TaskError::Validation("No round data".into()));
            }
            let i = rounds.len() - 1;
            rounds[i]["phase"] = Value::String("cross-review".into());
            result["phase"] = Value::String("cross-review".into());
        }
        "synthesize" => {
            if rounds.is_empty() {
                return Err(TaskError::Validation("No round data".into()));
            }
            let i = rounds.len() - 1;
            rounds[i]["phase"] = Value::String("synthesis".into());
            result["phase"] = Value::String("synthesis".into());
        }
        "status" => {
            if rounds.is_empty() {
                return Ok(json!({"action": "status", "rounds": 0}));
            }
            let i = rounds.len() - 1;
            let phase = rounds[i].get("phase").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let responses: Vec<Value> = rounds[i]
                .get("responses")
                .and_then(|v| v.as_array().cloned())
                .unwrap_or_default();
            let responded: HashSet<String> = responses
                .iter()
                .filter(|r| r.get("phase").and_then(|p| p.as_str()) == Some(&phase))
                .filter_map(|r| r.get("debater_id").and_then(|v| v.as_str().map(String::from)))
                .collect();
            let pending: Vec<String> = debaters
                .iter()
                .filter_map(|d| d.get("id").and_then(|v| v.as_str().map(String::from)))
                .filter(|id| !responded.contains(id))
                .collect();
            result["round_number"] = rounds[i].get("round_number").cloned().unwrap_or(Value::Null);
            result["phase"] = Value::String(phase);
            result["responded"] = json!(responded.into_iter().collect::<Vec<String>>());
            result["pending"] = json!(pending);
        }
        other => return Err(TaskError::Validation(format!("Unknown round action: {other}"))),
    }

    proj["rounds"] = Value::Array(rounds);
    save_project(pool, project_name, &proj).await?;
    Ok(result)
}

pub async fn reset_project(pool: &SqlitePool, project_name: &str) -> Result<(), TaskError> {
    let mut proj = load_project(pool, project_name).await?;
    let mode = proj.get("mode").and_then(|v| v.as_str()).unwrap_or("").to_string();
    match mode.as_str() {
        "linear" => {
            if let Some(stages) = proj.get_mut("stages").and_then(|v| v.as_array_mut()) {
                for s in stages.iter_mut() {
                    s["status"] = Value::String("pending".into());
                    s["result"] = Value::String("".into());
                    s["assigned_at"] = Value::String("".into());
                    s["completed_at"] = Value::String("".into());
                }
            }
            proj["current_stage"] = json!(0);
        }
        "dag" => {
            if let Some(tasks) = proj.get_mut("tasks").and_then(|v| v.as_array_mut()) {
                for t in tasks.iter_mut() {
                    t["status"] = Value::String("pending".into());
                    t["result"] = Value::String("".into());
                    t["assigned_at"] = Value::String("".into());
                    t["completed_at"] = Value::String("".into());
                }
            }
        }
        "debate" => {
            proj["rounds"] = Value::Array(vec![]);
        }
        _ => {}
    }
    save_project(pool, project_name, &proj).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ready_tasks_excludes_done_and_blocked() {
        let proj = json!({
            "tasks": [
                {"id": "a", "status": "done",    "dependencies": []},
                {"id": "b", "status": "pending", "dependencies": ["a"]},
                {"id": "c", "status": "pending", "dependencies": ["b"]},
                {"id": "d", "status": "pending", "dependencies": []},
            ]
        });
        let ready_vals = compute_ready_tasks(&proj);
        let ready: Vec<String> = ready_vals
            .iter()
            .filter_map(|t| t.get("id").and_then(|v| v.as_str()).map(String::from))
            .collect();
        assert!(ready.iter().any(|s| s == "b"));
        assert!(ready.iter().any(|s| s == "d"));
        assert!(!ready.iter().any(|s| s == "c"));
    }

    #[test]
    fn cycle_detected() {
        let proj = json!({
            "tasks": [
                {"id": "a", "status": "pending", "dependencies": ["b"]},
                {"id": "b", "status": "pending", "dependencies": ["a"]},
            ]
        });
        let cycles = detect_cycles(&proj);
        assert!(!cycles.is_empty());
    }

    #[test]
    fn no_cycle_diamond() {
        let proj = json!({
            "tasks": [
                {"id": "a", "status": "pending", "dependencies": []},
                {"id": "b", "status": "pending", "dependencies": ["a"]},
                {"id": "c", "status": "pending", "dependencies": ["a"]},
                {"id": "d", "status": "pending", "dependencies": ["b", "c"]},
            ]
        });
        assert!(detect_cycles(&proj).is_empty());
    }
}

