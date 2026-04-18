/// Layer 3 AI repair — stub in Phase C.
///
/// Full implementation requires:
/// 1. tmux-relay pane pool (pane_pool.sh)
/// 2. `claude -p <prompt>` dispatch
/// 3. signal file watching (`/tmp/sentinel-repair-{service}-{ts}`)
/// 4. 600s timeout with outcome parsing
///
/// For Phase C MVP, this returns PaneUnavailable so Layer 1+2 failures
/// correctly escalate. Future work will wire it via tmux-relay.

pub enum Outcome {
    Dispatched(String), // pane id
    PaneUnavailable,
    Disabled,
}

pub async fn dispatch(service: &str) -> Outcome {
    tracing::info!(
        service,
        "Layer 3 AI repair invoked — stub returns PaneUnavailable (Phase C MVP)"
    );
    Outcome::PaneUnavailable
}
