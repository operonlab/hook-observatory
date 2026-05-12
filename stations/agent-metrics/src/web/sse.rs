//! Server-Sent Events endpoint — single stream replacing 5 setInterval polls.
//!
//! Mirrors `agent_metrics.routes.events` (Python). Subscribers receive any of
//! these named events as soon as a producer emits them:
//!   - `connected`  — initial handshake on subscribe
//!   - `system`     — sysmon snapshot (sysmon_loop, ~5s)
//!   - `quota`      — LLM quota refresh (sysmon_loop quota merge, ~60s)
//!   - `sessions`   — active session list (aggregator, after each flush)
//!   - `usage`      — budget/trends invalidation tick (aggregator, ~60s)
//!   - `operations` — maestro dispatch completion (post run_dispatch)
//!
//! Producers call `EventBus::emit(...)`. Slow consumers that lag get dropped
//! silently — the broadcast channel is bounded at construction time.

use axum::extract::State;
use axum::response::sse::{Event, KeepAlive, Sse};
use futures::stream::{self, Stream, StreamExt};
use std::convert::Infallible;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::broadcast;
use tokio_stream::wrappers::BroadcastStream;

use crate::web::AppState;

#[derive(Clone, Debug)]
pub struct SseMessage {
    pub event: &'static str,
    pub data: serde_json::Value,
}

/// Broadcast channel wrapper. Cheap to `clone()` — internally an `Arc`.
#[derive(Clone)]
pub struct EventBus {
    inner: Arc<broadcast::Sender<SseMessage>>,
}

impl EventBus {
    pub fn new(capacity: usize) -> Self {
        let (tx, _rx) = broadcast::channel(capacity);
        Self { inner: Arc::new(tx) }
    }

    /// Emit one event. Returns the number of live subscribers (0 if nobody is
    /// listening — callers should treat it as a no-op success).
    pub fn emit(&self, event: &'static str, data: serde_json::Value) {
        let _ = self.inner.send(SseMessage { event, data });
    }

    pub fn subscribe(&self) -> broadcast::Receiver<SseMessage> {
        self.inner.subscribe()
    }
}

/// GET /events/stream — Server-Sent Events handler.
pub async fn stream_handler(
    State(state): State<AppState>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let rx = state.event_bus.subscribe();
    let upstream = BroadcastStream::new(rx).filter_map(|res| async move {
        match res {
            Ok(msg) => Some(Ok::<_, Infallible>(
                Event::default()
                    .event(msg.event)
                    .data(msg.data.to_string()),
            )),
            // Lagged (slow consumer) — drop silently, browser will resync via polling.
            Err(_) => None,
        }
    });

    let init = stream::once(async {
        Ok::<_, Infallible>(Event::default().event("connected").data("{}"))
    });

    Sse::new(init.chain(upstream)).keep_alive(
        KeepAlive::new()
            .interval(Duration::from_secs(30))
            .text("keepalive"),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn emit_reaches_subscriber() {
        let bus = EventBus::new(8);
        let mut rx = bus.subscribe();
        bus.emit("system", serde_json::json!({"cpu": 12}));
        let msg = rx.recv().await.expect("recv");
        assert_eq!(msg.event, "system");
        assert_eq!(msg.data["cpu"], 12);
    }

    #[tokio::test]
    async fn emit_with_no_subscribers_is_noop() {
        let bus = EventBus::new(8);
        bus.emit("ghost", serde_json::json!({}));
    }

    #[tokio::test]
    async fn lag_keeps_newest_after_skip() {
        // tokio broadcast: when capacity is exceeded, recv() yields a Lagged
        // error first (skip count), then continues from the oldest still-live
        // message. We assert that the *newest* messages survive.
        let bus = EventBus::new(2);
        let mut rx = bus.subscribe();
        for i in 0..5 {
            bus.emit("tick", serde_json::json!({"i": i}));
        }
        let mut received: Vec<i64> = Vec::new();
        for _ in 0..6 {
            match tokio::time::timeout(Duration::from_millis(50), rx.recv()).await {
                Ok(Ok(m)) => received.push(m.data["i"].as_i64().unwrap_or(-1)),
                Ok(Err(_lagged_or_closed)) => continue,
                Err(_timeout) => break,
            }
        }
        assert!(received.contains(&3), "got {:?}", received);
        assert!(received.contains(&4), "got {:?}", received);
    }
}
