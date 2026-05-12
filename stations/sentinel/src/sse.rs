use serde_json::Value;
use tokio::sync::broadcast;

#[derive(Clone, Debug)]
pub struct SseEvent {
    pub event: String,
    pub data: Value,
}

#[derive(Clone)]
pub struct SseHub {
    tx: broadcast::Sender<SseEvent>,
}

impl SseHub {
    pub fn new(capacity: usize) -> Self {
        let (tx, _rx) = broadcast::channel(capacity);
        Self { tx }
    }

    pub fn subscribe(&self) -> broadcast::Receiver<SseEvent> {
        self.tx.subscribe()
    }

    pub fn broadcast(&self, event: impl Into<String>, data: Value) {
        let _ = self.tx.send(SseEvent {
            event: event.into(),
            data,
        });
    }
}
