//! /maestro/* routes — dispatch + plan + runs + tier-stats + routing-table.

use super::AppState;
use crate::engines::{dispatch, routing, runs};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use chrono::Utc;
use futures::future::join_all;
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Debug, Deserialize)]
pub struct PlanRequest {
    pub task: String,
    #[serde(default)]
    pub pattern: Option<String>,
    #[serde(default = "default_budget")]
    pub budget: String,
    #[serde(default)]
    pub tier: Option<String>,
}
fn default_budget() -> String {
    "balanced".into()
}

#[derive(Debug, Deserialize)]
pub struct DispatchRequest {
    pub task: String,
    #[serde(default)]
    pub pattern: Option<String>,
    #[serde(default = "default_budget")]
    pub budget: String,
    #[serde(default)]
    pub cwd: String,
    #[serde(default)]
    pub timeout: Option<u64>,
    #[serde(default)]
    pub ratio: String,
    #[serde(default)]
    pub tier: Option<String>,
}

pub async fn plan(
    State(state): State<AppState>,
    Json(body): Json<PlanRequest>,
) -> Json<Value> {
    let mut analysis = routing::analyze_task(&state.settings, &body.task, &body.budget);
    if let Some(p) = body.pattern {
        analysis.recommended_pattern = p.clone();
        if p == "pipeline" {
            let primary = analysis.categories.first().cloned().unwrap_or_else(|| "code_generation".into());
            let templates = routing::get_pipeline_templates(&state.settings);
            analysis.phases = templates
                .get(&primary)
                .or_else(|| templates.get("code_generation"))
                .cloned()
                .unwrap_or_default();
        }
    }
    let tier = routing::resolve_tier(&state.settings, &analysis, body.tier.as_deref()).await;
    analysis.recommended_tier = tier;
    let explicit = routing::detect_explicit_clis(&body.task);
    if !explicit.is_empty() {
        analysis.explicit_clis = Some(explicit);
    }
    Json(serde_json::to_value(&analysis).unwrap_or(Value::Null))
}

pub async fn run_dispatch(
    State(state): State<AppState>,
    Json(body): Json<DispatchRequest>,
) -> Json<Value> {
    let mut analysis = routing::analyze_task(&state.settings, &body.task, &body.budget);
    if let Some(p) = &body.pattern {
        analysis.recommended_pattern = p.clone();
    }
    let tier = routing::resolve_tier(&state.settings, &analysis, body.tier.as_deref()).await;
    analysis.recommended_tier = tier.clone();
    let explicit = routing::detect_explicit_clis(&body.task);

    let cwd_opt = if body.cwd.is_empty() { None } else { Some(body.cwd.as_str()) };
    let cwd_for_run = if body.cwd.is_empty() { ".".to_string() } else { body.cwd.clone() };
    let mut run = runs::MaestroRun::new_with_defaults(
        analysis.recommended_pattern.clone(),
        body.task.clone(),
        body.budget.clone(),
        cwd_for_run,
        tier.clone(),
        analysis.phases.clone(),
    );
    let _ = runs::save_run(&state.pool, &run).await;

    let timeout = body.timeout.unwrap_or(state.settings.default_timeout_s);

    let pattern = analysis.recommended_pattern.clone();
    if pattern == "solo" || (pattern != "pipeline" && pattern != "race") {
        let cli = explicit
            .first()
            .cloned()
            .unwrap_or_else(|| {
                routing::route_to_cli(
                    &state.settings,
                    analysis.categories.first().map(|s| s.as_str()).unwrap_or("code_generation"),
                    &body.budget,
                )
            });
        let r = dispatch::dispatch_by_tier(&state.settings, &tier, &cli, &body.task, cwd_opt, timeout).await;
        run.results = vec![serde_json::to_value(&r).unwrap_or(Value::Null)];
    } else if pattern == "pipeline" {
        for phase in &analysis.phases {
            // analysis.phases is Vec<serde_yaml::Value>; access via serde_yaml API
            let role = phase
                .get("role")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let cli = phase
                .get("cli")
                .and_then(|v| v.as_str())
                .unwrap_or("claude");
            let prompt = format!("[{role}] {}", body.task);
            let r = dispatch::dispatch_by_tier(&state.settings, &tier, cli, &prompt, cwd_opt, timeout).await;
            let v = serde_json::to_value(&r).unwrap_or(Value::Null);
            let failed = v.get("status").and_then(|s| s.as_str()) == Some("failed");
            run.results.push(v);
            if failed {
                break;
            }
        }
    } else {
        // race
        let clis: Vec<String> = if explicit.len() >= 2 {
            explicit.clone()
        } else {
            vec!["claude".into(), "codex".into(), "gemini".into()]
        };
        let futures = clis.iter().map(|cli| {
            dispatch::dispatch_by_tier(&state.settings, &tier, cli, &body.task, cwd_opt, timeout)
        });
        let results = join_all(futures).await;
        for r in results {
            run.results.push(serde_json::to_value(&r).unwrap_or(Value::Null));
        }
    }

    let completed = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false);
    let started_dt = chrono::DateTime::parse_from_rfc3339(&run.started_at).ok();
    let completed_dt = chrono::DateTime::parse_from_rfc3339(&completed).ok();
    let duration = match (started_dt, completed_dt) {
        (Some(s), Some(c)) => round1((c - s).num_milliseconds() as f64 / 1000.0),
        _ => 0.0,
    };
    run.completed_at = completed;
    run.duration_s = duration;
    run.status = "completed".into();
    let _ = runs::save_run(&state.pool, &run).await;

    let mut report = runs::generate_report(&run);
    if let Some(obj) = report.as_object_mut() {
        obj.insert("tier".into(), Value::String(tier));
    }
    state.event_bus.emit(
        "operations",
        serde_json::json!({
            "name": run.name,
            "pattern": run.pattern,
            "status": run.status,
            "duration_s": run.duration_s,
            "completed_at": run.completed_at,
        }),
    );
    Json(report)
}

#[derive(Debug, Deserialize)]
pub struct ListRunsQuery {
    #[serde(default = "default_runs_limit")]
    pub limit: i64,
}
fn default_runs_limit() -> i64 {
    50
}

pub async fn list_runs(
    State(state): State<AppState>,
    Query(q): Query<ListRunsQuery>,
) -> Json<Value> {
    let rows = runs::list_runs(&state.pool, q.limit).await.unwrap_or_default();
    Json(serde_json::to_value(rows).unwrap_or(Value::Null))
}

pub async fn get_run(
    State(state): State<AppState>,
    Path(name): Path<String>,
) -> Result<Json<Value>, StatusCode> {
    match runs::load_run(&state.pool, &name).await {
        Ok(Some(v)) => Ok(Json(v)),
        Ok(None) => Err(StatusCode::NOT_FOUND),
        Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
    }
}

#[derive(Debug, Deserialize)]
pub struct TierStatsQuery {
    #[serde(default = "default_days")]
    pub days: i64,
}
fn default_days() -> i64 {
    30
}

pub async fn tier_stats(
    State(state): State<AppState>,
    Query(q): Query<TierStatsQuery>,
) -> Json<Value> {
    let v = runs::tier_stats(&state.pool, q.days).await.unwrap_or(Value::Null);
    Json(v)
}

pub async fn routing_table(State(state): State<AppState>) -> Json<Value> {
    let routing = routing::get_cli_routing(&state.settings);
    let templates = routing::get_pipeline_templates(&state.settings);
    let templates_json: serde_json::Map<String, Value> = templates
        .into_iter()
        .map(|(k, v)| {
            let arr: Vec<Value> = v
                .into_iter()
                .map(|y| serde_yaml::from_value::<Value>(y).unwrap_or(Value::Null))
                .collect();
            (k, Value::Array(arr))
        })
        .collect();
    let tier_routing = routing::get_tier_routing(&state.settings);
    let tier_routing_json: Value = serde_yaml::from_value(tier_routing).unwrap_or(Value::Null);
    let tier_keywords = routing::get_tier_keywords(&state.settings);
    Json(json!({
        "routing": routing,
        "templates": templates_json,
        "tier_routing": tier_routing_json,
        "tier_keywords": tier_keywords,
    }))
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}
