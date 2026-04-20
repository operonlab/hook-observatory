//! /projects/* routes — team-task project CRUD + tasks + debaters + rounds.

use super::AppState;
use crate::engines::tasks::{self, TaskError};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};

fn map_err(e: TaskError) -> (StatusCode, Json<Value>) {
    let code = match &e {
        TaskError::NotFound(_) => StatusCode::NOT_FOUND,
        TaskError::Exists(_) => StatusCode::BAD_REQUEST,
        TaskError::Validation(_) => StatusCode::UNPROCESSABLE_ENTITY,
    };
    (code, Json(json!({"detail": e.to_string()})))
}

pub async fn list_projects(State(state): State<AppState>) -> Json<Value> {
    let rows = tasks::list_projects(&state.pool).await.unwrap_or_default();
    Json(serde_json::to_value(rows).unwrap_or(Value::Null))
}

#[derive(Debug, Deserialize)]
pub struct ProjectCreate {
    pub name: String,
    #[serde(default = "default_mode")]
    pub mode: String,
    #[serde(default)]
    pub goal: String,
    #[serde(default)]
    pub pipeline: String,
    #[serde(default)]
    pub workspace: String,
}
fn default_mode() -> String {
    "dag".into()
}

pub async fn create_project(
    State(state): State<AppState>,
    Json(body): Json<ProjectCreate>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let proj = tasks::init_project(
        &state.pool,
        &body.name,
        &body.mode,
        &body.goal,
        &body.pipeline,
        &body.workspace,
        false,
    )
    .await
    .map_err(map_err)?;
    Ok(Json(json!({"status": "created", "project": proj})))
}

pub async fn get_project(
    State(state): State<AppState>,
    Path(name): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let v = tasks::get_status(&state.pool, &name).await.map_err(map_err)?;
    Ok(Json(v))
}

#[derive(Debug, Deserialize)]
pub struct TaskAdd {
    pub task_id: String,
    #[serde(default)]
    pub agent: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub deps: String,
}

pub async fn add_task(
    State(state): State<AppState>,
    Path(name): Path<String>,
    Json(body): Json<TaskAdd>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let t = tasks::add_task(&state.pool, &name, &body.task_id, &body.agent, &body.description, &body.deps)
        .await
        .map_err(map_err)?;
    Ok(Json(json!({"status": "added", "task": t})))
}

pub async fn ready_tasks(
    State(state): State<AppState>,
    Path(name): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let v = tasks::get_ready_tasks(&state.pool, &name).await.map_err(map_err)?;
    Ok(Json(serde_json::to_value(v).unwrap_or(Value::Null)))
}

pub async fn next_stage(
    State(state): State<AppState>,
    Path(name): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    match tasks::get_next_stage(&state.pool, &name).await.map_err(map_err)? {
        Some(s) => Ok(Json(s)),
        None => Ok(Json(json!({"status": "all_complete"}))),
    }
}

#[derive(Debug, Deserialize)]
pub struct TaskUpdate {
    pub status: String,
}

pub async fn update_task(
    State(state): State<AppState>,
    Path((name, task_id)): Path<(String, String)>,
    Json(body): Json<TaskUpdate>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let v = tasks::update_task_status(&state.pool, &name, &task_id, &body.status)
        .await
        .map_err(map_err)?;
    Ok(Json(v))
}

#[derive(Debug, Deserialize)]
pub struct TaskResult {
    pub text: String,
}

pub async fn record_result(
    State(state): State<AppState>,
    Path((name, task_id)): Path<(String, String)>,
    Json(body): Json<TaskResult>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    tasks::record_result(&state.pool, &name, &task_id, &body.text)
        .await
        .map_err(map_err)?;
    Ok(Json(json!({"status": "recorded"})))
}

#[derive(Debug, Deserialize)]
pub struct DebaterAdd {
    pub debater_id: String,
    #[serde(default)]
    pub agent: String,
    #[serde(default)]
    pub perspective: String,
}

pub async fn add_debater(
    State(state): State<AppState>,
    Path(name): Path<String>,
    Json(body): Json<DebaterAdd>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let d = tasks::add_debater(&state.pool, &name, &body.debater_id, &body.agent, &body.perspective)
        .await
        .map_err(map_err)?;
    Ok(Json(json!({"status": "added", "debater": d})))
}

#[derive(Debug, Deserialize)]
pub struct RoundAction {
    pub action: String,
    #[serde(default)]
    pub debater_id: String,
    #[serde(default)]
    pub text: String,
}

pub async fn manage_round(
    State(state): State<AppState>,
    Path(name): Path<String>,
    Json(body): Json<RoundAction>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let v = tasks::manage_round(&state.pool, &name, &body.action, &body.debater_id, &body.text)
        .await
        .map_err(map_err)?;
    Ok(Json(v))
}

pub async fn reset_project(
    State(state): State<AppState>,
    Path(name): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    tasks::reset_project(&state.pool, &name).await.map_err(map_err)?;
    Ok(Json(json!({"status": "reset"})))
}
