use crate::error::SentinelError;
use crate::models::{now_epoch, State};
use crate::sse::SseEvent;
use crate::tasks::light_loop::build_status_payload;
use crate::AppState;
use axum::body::Body;
use axum::extract::{Path, Query, State as AxumState};
use axum::http::{HeaderMap, Method, StatusCode, Uri};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::IntoResponse;
use axum::Json;
use futures::stream::Stream;
use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::Row;
use std::convert::Infallible;
use std::time::Duration;
use uuid::Uuid;

// ─── Status ────────────────────────────────────────────────

pub async fn status_all(AxumState(s): AxumState<AppState>) -> Json<Value> {
    Json(build_status_payload(&s.engine))
}

pub async fn status_one(
    AxumState(s): AxumState<AppState>,
    Path(service): Path<String>,
) -> Result<Json<Value>, SentinelError> {
    let t = s.engine.get_or_create(&service);
    if t.light_status.is_none() {
        return Err(SentinelError::NotFound(format!("no data for {}", service)));
    }
    Ok(Json(json!({
        "service": t.service,
        "state": t.state,
        "light_status": t.light_status,
        "response_ms": t.response_ms,
        "last_light_check": t.last_light_check,
        "first_failure_at": t.first_failure_at,
        "agent_id": t.agent_id,
        "incident_id": t.incident_id,
    })))
}

pub async fn health() -> Json<Value> {
    Json(json!({ "status": "healthy", "service": "sentinel", "version": env!("CARGO_PKG_VERSION") }))
}

// ─── Agent Operations ──────────────────────────────────────

#[derive(Deserialize)]
pub struct NotifyBody {
    pub service: String,
    pub agent_id: String,
    pub action: Option<String>,
    pub pid: Option<i32>,
    pub estimated_duration: Option<u64>,
}

pub async fn notify(
    AxumState(s): AxumState<AppState>,
    Json(body): Json<NotifyBody>,
) -> Result<Json<Value>, SentinelError> {
    let estimated = body.estimated_duration.unwrap_or(300);
    s.engine
        .notify_agent(&body.service, body.agent_id.clone(), body.pid, estimated)
        .map_err(SentinelError::Internal)?;

    let id = Uuid::now_v7().to_string();
    sqlx::query(
        "INSERT INTO active_operations (id, service, action, agent_id, pid, estimated_duration) \
         VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(&body.service)
    .bind(body.action.unwrap_or_else(|| "maintenance".into()))
    .bind(&body.agent_id)
    .bind(body.pid)
    .bind(estimated as i64)
    .execute(&s.pool)
    .await?;

    Ok(Json(json!({"ok": true, "operation_id": id})))
}

#[derive(Deserialize)]
pub struct ResolveBody {
    pub service: String,
    pub agent_id: String,
    pub result: Option<String>,
}

pub async fn resolve(
    AxumState(s): AxumState<AppState>,
    Json(body): Json<ResolveBody>,
) -> Result<Json<Value>, SentinelError> {
    s.engine
        .resolve_agent(&body.service, &body.agent_id)
        .map_err(SentinelError::Internal)?;

    sqlx::query(
        "UPDATE active_operations SET resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), result = ? \
         WHERE service = ? AND agent_id = ? AND resolved_at IS NULL",
    )
    .bind(body.result.unwrap_or_else(|| "success".into()))
    .bind(&body.service)
    .bind(&body.agent_id)
    .execute(&s.pool)
    .await?;

    Ok(Json(json!({"ok": true})))
}

pub async fn operations(AxumState(s): AxumState<AppState>) -> Result<Json<Value>, SentinelError> {
    let rows = sqlx::query(
        "SELECT id, service, action, agent_id, pid, estimated_duration, created_at \
         FROM active_operations WHERE resolved_at IS NULL ORDER BY created_at DESC",
    )
    .fetch_all(&s.pool)
    .await?;

    let ops: Vec<Value> = rows
        .iter()
        .map(|r| {
            json!({
                "id": r.get::<String, _>("id"),
                "service": r.get::<String, _>("service"),
                "action": r.get::<String, _>("action"),
                "agent_id": r.get::<String, _>("agent_id"),
                "pid": r.get::<Option<i64>, _>("pid"),
                "estimated_duration": r.get::<i64, _>("estimated_duration"),
                "created_at": r.get::<String, _>("created_at"),
            })
        })
        .collect();
    Ok(Json(json!({"operations": ops, "count": ops.len()})))
}

// ─── Incidents ────────────────────────────────────────────

#[derive(Deserialize, Default)]
pub struct IncidentsQuery {
    pub page: Option<i64>,
    pub page_size: Option<i64>,
    // legacy aliases (keep working for non-UI consumers)
    pub limit: Option<i64>,
    pub offset: Option<i64>,
    pub service: Option<String>,
    pub status: Option<String>,
}

pub async fn incidents_list(
    AxumState(s): AxumState<AppState>,
    Query(q): Query<IncidentsQuery>,
) -> Result<Json<Value>, SentinelError> {
    let page_size = q
        .page_size
        .or(q.limit)
        .unwrap_or(20)
        .clamp(1, 500);
    let page = q.page.unwrap_or(1).max(1);
    let offset = q.offset.unwrap_or((page - 1) * page_size).max(0);

    let mut where_sql = String::from(" WHERE 1=1");
    if q.service.is_some() {
        where_sql.push_str(" AND service = ?");
    }
    if q.status.is_some() {
        where_sql.push_str(" AND status = ?");
    }

    let count_sql = format!("SELECT COUNT(*) as n FROM incidents{}", where_sql);
    let mut count_q = sqlx::query(&count_sql);
    if let Some(svc) = &q.service {
        count_q = count_q.bind(svc);
    }
    if let Some(st) = &q.status {
        count_q = count_q.bind(st);
    }
    let total: i64 = count_q.fetch_one(&s.pool).await?.get("n");

    let list_sql = format!(
        "SELECT id, service, status, severity, title, created_at, resolved_at FROM incidents{} \
         ORDER BY created_at DESC LIMIT ? OFFSET ?",
        where_sql
    );
    let mut list_q = sqlx::query(&list_sql);
    if let Some(svc) = &q.service {
        list_q = list_q.bind(svc);
    }
    if let Some(st) = &q.status {
        list_q = list_q.bind(st);
    }
    list_q = list_q.bind(page_size).bind(offset);

    let rows = list_q.fetch_all(&s.pool).await?;
    let items: Vec<Value> = rows
        .iter()
        .map(|r| {
            json!({
                "id": r.get::<String, _>("id"),
                "service": r.get::<String, _>("service"),
                "status": r.get::<String, _>("status"),
                "severity": r.get::<String, _>("severity"),
                "title": r.get::<String, _>("title"),
                "created_at": r.get::<String, _>("created_at"),
                "resolved_at": r.get::<Option<String>, _>("resolved_at"),
            })
        })
        .collect();

    let total_pages = if page_size > 0 {
        (total + page_size - 1) / page_size
    } else {
        0
    };

    Ok(Json(json!({
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        // legacy aliases
        "incidents": items.clone(),
        "count": items.len(),
    })))
}

pub async fn incident_detail(
    AxumState(s): AxumState<AppState>,
    Path(id): Path<String>,
) -> Result<Json<Value>, SentinelError> {
    let row = sqlx::query("SELECT * FROM incidents WHERE id = ?")
        .bind(&id)
        .fetch_optional(&s.pool)
        .await?
        .ok_or_else(|| SentinelError::NotFound(format!("incident {} not found", id)))?;

    Ok(Json(json!({
        "id": row.get::<String, _>("id"),
        "service": row.get::<String, _>("service"),
        "status": row.get::<String, _>("status"),
        "severity": row.get::<String, _>("severity"),
        "title": row.get::<String, _>("title"),
        "detail": row.get::<Option<String>, _>("detail"),
        "diagnosis": row.get::<Option<String>, _>("diagnosis"),
        "repair_result": row.get::<Option<String>, _>("repair_result"),
        "created_at": row.get::<String, _>("created_at"),
        "resolved_at": row.get::<Option<String>, _>("resolved_at"),
    })))
}

pub async fn uptime(AxumState(s): AxumState<AppState>) -> Result<Json<Value>, SentinelError> {
    let rows = sqlx::query(
        "SELECT service, \
         substr(created_at, 1, 10) as day, \
         SUM(CASE WHEN status IN ('healthy','operational','skipped') THEN 1 ELSE 0 END) as healthy, \
         COUNT(*) as total \
         FROM health_checks \
         WHERE created_at >= datetime('now','-90 days') \
         GROUP BY service, day \
         ORDER BY service, day",
    )
    .fetch_all(&s.pool)
    .await?;

    use std::collections::BTreeMap;
    let mut per_service: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    let mut totals: BTreeMap<String, (i64, i64)> = BTreeMap::new();

    for r in &rows {
        let svc: String = r.get("service");
        let day: String = r.get("day");
        let healthy: i64 = r.get("healthy");
        let total: i64 = r.get("total");
        let pct = if total > 0 {
            (healthy as f64 / total as f64) * 100.0
        } else {
            0.0
        };
        // Map daily uptime % to the frontend's tl-cell colour enum
        // (operational = green, degraded = yellow, outage = red).
        let day_status = if total == 0 {
            "no_data"
        } else if pct >= 99.0 {
            "operational"
        } else if pct >= 90.0 {
            "degraded"
        } else {
            "outage"
        };
        per_service.entry(svc.clone()).or_default().push(json!({
            "date": day,
            "uptime_pct": (pct * 100.0).round() / 100.0,
            "healthy_checks": healthy,
            "total_checks": total,
            "status": day_status,
        }));
        let agg = totals.entry(svc).or_insert((0, 0));
        agg.0 += healthy;
        agg.1 += total;
    }

    let items: Vec<Value> = per_service
        .into_iter()
        .map(|(svc, days)| {
            let (h, t) = totals.get(&svc).copied().unwrap_or((0, 0));
            let pct = if t > 0 {
                (h as f64 / t as f64) * 100.0
            } else {
                0.0
            };
            json!({
                "service": svc,
                "uptime_pct": (pct * 100.0).round() / 100.0,
                "healthy_checks": h,
                "total_checks": t,
                "days": days,
            })
        })
        .collect();
    Ok(Json(json!({"period_days": 90, "services": items})))
}

// ─── Subscriptions ────────────────────────────────────────

#[derive(Deserialize)]
pub struct SubscribeBody {
    pub url: String,
    pub events: Option<Vec<String>>,
}

pub async fn subscribe(
    AxumState(s): AxumState<AppState>,
    Json(body): Json<SubscribeBody>,
) -> Result<Json<Value>, SentinelError> {
    let id = Uuid::now_v7().to_string();
    let events = body.events.unwrap_or_else(|| vec!["*".into()]);
    let events_json = serde_json::to_string(&events).unwrap();

    sqlx::query("INSERT INTO subscriptions (id, url, events, active) VALUES (?, ?, ?, 1)")
        .bind(&id)
        .bind(&body.url)
        .bind(&events_json)
        .execute(&s.pool)
        .await?;

    Ok(Json(json!({"id": id, "url": body.url, "events": events})))
}

// ─── SSE ──────────────────────────────────────────────────

pub async fn sse_events(
    AxumState(s): AxumState<AppState>,
) -> impl IntoResponse {
    let rx = s.sse.subscribe();
    let stream = async_stream::stream! {
        yield Ok(Event::default().event("connected").data("{}"));
        let mut rx = rx;
        loop {
            match tokio::time::timeout(Duration::from_secs(30), rx.recv()).await {
                Ok(Ok(SseEvent { event, data })) => {
                    yield Ok(Event::default().event(event).data(data.to_string()));
                }
                Ok(Err(_)) => break,
                Err(_) => {
                    yield Ok::<_, Infallible>(Event::default().comment("keepalive"));
                }
            }
        }
    };
    let sse = Sse::new(stream).keep_alive(KeepAlive::new());
    // Hint upstream proxies (nginx, CloudFlare) not to buffer or transform
    // the event stream — buffering is the usual cause of QUIC RTO accumulation
    // on long-lived idle SSE connections.
    (
        [
            (axum::http::header::CACHE_CONTROL, "no-cache, no-transform"),
            (axum::http::HeaderName::from_static("x-accel-buffering"), "no"),
        ],
        sse,
    )
}

// ─── Sysmon proxy ─────────────────────────────────────────

pub async fn sysmon_proxy(
    AxumState(s): AxumState<AppState>,
    method: Method,
    Path(subpath): Path<String>,
    headers: HeaderMap,
    uri: Uri,
    body: Body,
) -> Result<axum::response::Response, SentinelError> {
    let qs = uri.query().map(|q| format!("?{}", q)).unwrap_or_default();
    let target = format!("{}/{}{}", s.cfg.sysmon_url.trim_end_matches('/'), subpath, qs);

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| SentinelError::Internal(e.into()))?;

    let body_bytes = axum::body::to_bytes(body, 5 * 1024 * 1024)
        .await
        .map_err(|e| SentinelError::BadRequest(e.to_string()))?;

    let mut req = client.request(method, &target);
    if !body_bytes.is_empty() {
        req = req.body(body_bytes.to_vec());
    }
    for (k, v) in headers.iter() {
        if k.as_str().starts_with("host") || k.as_str().starts_with("content-length") {
            continue;
        }
        req = req.header(k, v);
    }

    let resp = req.send().await.map_err(|e| SentinelError::Internal(e.into()))?;
    let status = resp.status();
    let resp_bytes = resp
        .bytes()
        .await
        .map_err(|e| SentinelError::Internal(e.into()))?;

    let mut builder = axum::response::Response::builder()
        .status(StatusCode::from_u16(status.as_u16()).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR));
    builder
        .body(Body::from(resp_bytes))
        .map_err(|e| SentinelError::Internal(anyhow::anyhow!("build response: {}", e)))
        .map(|r| r.into_response())
}
