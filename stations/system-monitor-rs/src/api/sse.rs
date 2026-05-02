//! Server-Sent Events stream + background broadcast loops.

use axum::{
    extract::State,
    response::sse::{Event, KeepAlive, Sse},
};
use futures_util::stream::Stream;
use std::convert::Infallible;
use std::time::Duration;
use tokio::sync::broadcast;

use super::AppState;
use crate::collector::{collect_all, disk_fast};

#[derive(Clone, Debug)]
pub struct BroadcastEvent {
    pub event: String,
    pub data: String,
}

#[derive(Clone)]
pub struct Broadcaster {
    tx: broadcast::Sender<BroadcastEvent>,
}

impl Broadcaster {
    pub fn new() -> Self {
        let (tx, _rx) = broadcast::channel(64);
        Self { tx }
    }
    pub fn subscribe(&self) -> broadcast::Receiver<BroadcastEvent> {
        self.tx.subscribe()
    }
    pub fn send(&self, evt: BroadcastEvent) {
        let _ = self.tx.send(evt);
    }
}

pub async fn stream(
    State(s): State<AppState>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let rx = s.broadcaster.subscribe();
    let stream = async_stream::stream! {
        let mut rx = rx;
        loop {
            match rx.recv().await {
                Ok(evt) => yield Ok::<_, Infallible>(
                    Event::default().event(evt.event).data(evt.data)
                ),
                Err(broadcast::error::RecvError::Lagged(_)) => continue,
                Err(broadcast::error::RecvError::Closed) => break,
            }
        }
    };
    Sse::new(stream).keep_alive(KeepAlive::new().interval(Duration::from_secs(30)))
}

pub fn spawn_dashboard_loop(state: AppState) {
    let interval = state.cfg.dashboard_broadcast_interval_secs.max(5);
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(Duration::from_secs(interval));
        loop {
            ticker.tick().await;
            if let Ok(snapshot) = collect_all(&state.collector).await {
                let payload = serde_json::to_string(&snapshot).unwrap_or_else(|_| "{}".into());
                state.broadcaster.send(BroadcastEvent {
                    event: "dashboard".into(),
                    data: payload,
                });
            }
        }
    });
}

pub fn spawn_disk_loop(state: AppState) {
    let interval = state.cfg.disk_broadcast_interval_secs.max(30);
    tokio::spawn(async move {
        // Stagger: wait 15s before first emission so /events/stream subscribers
        // don't get pummeled at connect time.
        tokio::time::sleep(Duration::from_secs(15)).await;
        let mut ticker = tokio::time::interval(Duration::from_secs(interval));
        loop {
            ticker.tick().await;
            if let Ok(disk) = disk_fast::collect(&state.collector).await {
                let payload = serde_json::to_string(&disk).unwrap_or_else(|_| "{}".into());
                state.broadcaster.send(BroadcastEvent {
                    event: "disk".into(),
                    data: payload,
                });
            }
        }
    });
}
