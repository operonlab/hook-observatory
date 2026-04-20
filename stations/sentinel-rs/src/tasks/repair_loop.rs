use crate::models::{now_epoch, State};
use crate::remediation::Remediator;
use crate::state::InterventionEngine;
use std::sync::Arc;
use std::time::Duration;
use tokio::time::interval;
use tokio_util::sync::CancellationToken;

pub async fn run(
    engine: Arc<InterventionEngine>,
    remediator: Arc<Remediator>,
    cooldown_sec: u64,
    interval_sec: u64,
    token: CancellationToken,
) {
    let mut ticker = interval(Duration::from_secs(interval_sec));
    loop {
        tokio::select! {
            _ = token.cancelled() => {
                tracing::info!("repair_loop shutting down");
                return;
            }
            _ = ticker.tick() => {
                // 1. Resolve pending REPAIRING jobs (Layer 3 signal file check)
                remediator.check_pending_repairs().await;

                // 2. Dispatch fresh INTERVENING services
                let candidates: Vec<String> = engine
                    .all()
                    .into_iter()
                    .filter(|t| t.state == State::Intervening)
                    .filter(|t| {
                        t.last_notified_at == 0.0
                            || (now_epoch() - t.last_notified_at) >= cooldown_sec as f64
                    })
                    .map(|t| t.service)
                    .collect();

                for svc in candidates {
                    tracing::info!(service = %svc, "repair_loop dispatching");
                    let outcome = remediator.dispatch(&svc).await;
                    tracing::info!(service = %svc, ?outcome, "repair_loop outcome");
                }
            }
        }
    }
}
