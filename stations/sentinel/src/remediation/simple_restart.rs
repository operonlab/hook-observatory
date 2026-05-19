use std::time::Duration;
use tokio::process::Command;
use tokio::time::timeout;

/// Services that workshop_services.py can stop/start.
/// Mirrors Python remediation.py SIMPLE_RESTART_MAP (2026-04-18 snapshot).
pub const WORKSHOP_SERVICES: &[&str] = &[
    "core", "paper", "intelflow", "invest",
    // hook-observatory removed 2026-05-13 (Python dashboard archived)
    "session-channel", "system-monitor",
    "agent-metrics", "agent-vista", "litellm",
    "auto-survey", "capture-console", "anvil", "blog",
    "cronicle", "mcpproxy", "tmux-webui", "fleet",
    "stt", "tts", "ocr", "voice-gateway", "translate",
    "sentinel",
];

/// Docker container names keyed by sentinel service name.
pub const DOCKER_CONTAINERS: &[(&str, &str)] = &[
    ("postgres", "ws-infra-postgres-1"),
    ("redis", "ws-infra-redis-1"),
    ("rustfs", "ws-infra-rustfs-1"),
    ("bark", "ws-infra-bark-1"),
    ("qdrant", "ws-infra-qdrant-1"),
];

pub fn can_restart(service: &str) -> bool {
    WORKSHOP_SERVICES.contains(&service)
        || DOCKER_CONTAINERS.iter().any(|(k, _)| *k == service)
        || service == "orbstack"
}

pub async fn restart(service: &str) -> anyhow::Result<()> {
    if WORKSHOP_SERVICES.contains(&service) {
        return restart_workshop_service(service).await;
    }
    if let Some((_, container)) = DOCKER_CONTAINERS.iter().find(|(k, _)| *k == service) {
        return restart_docker(container).await;
    }
    if service == "orbstack" {
        return run_cmd("orbctl", &["start"]).await;
    }
    Err(anyhow::anyhow!("no restart path for {}", service))
}

async fn restart_workshop_service(name: &str) -> anyhow::Result<()> {
    let script = "/Users/joneshong/workshop/scripts/workshop_services.py";
    run_cmd("/Users/joneshong/.local/bin/python3", &[script, "stop", name]).await?;
    tokio::time::sleep(Duration::from_secs(3)).await;
    run_cmd("/Users/joneshong/.local/bin/python3", &[script, "start", name]).await?;
    Ok(())
}

async fn restart_docker(container: &str) -> anyhow::Result<()> {
    run_cmd("docker", &["restart", container]).await
}

async fn run_cmd(cmd: &str, args: &[&str]) -> anyhow::Result<()> {
    let out = timeout(
        Duration::from_secs(60),
        Command::new(cmd).args(args).output(),
    )
    .await
    .map_err(|_| anyhow::anyhow!("{} timed out", cmd))??;
    if !out.status.success() {
        return Err(anyhow::anyhow!(
            "{} {:?} failed: {}",
            cmd,
            args,
            String::from_utf8_lossy(&out.stderr)
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn workshop_services_restartable() {
        assert!(can_restart("core"));
        assert!(can_restart("blog"));
        assert!(can_restart("agent-metrics"));
    }

    #[test]
    fn docker_containers_restartable() {
        assert!(can_restart("postgres"));
        assert!(can_restart("redis"));
        assert!(can_restart("qdrant"));
    }

    #[test]
    fn orbstack_restartable() {
        assert!(can_restart("orbstack"));
    }

    #[test]
    fn unknown_services_not_restartable() {
        assert!(!can_restart("nginx"));
        assert!(!can_restart("unknown"));
        assert!(!can_restart("frontend"));
    }

    /// Audit shell checks (group="system" in registry.rs) are scripts, not services.
    /// They must NOT be in WORKSHOP_SERVICES — otherwise `restart` would try to
    /// stop/start a non-existent service via workshop_services.py.
    /// Combined with frontend::applicable() being false for them, the
    /// applicability gate in Remediator::dispatch escalates without dispatching
    /// the catch-all AI repair agent.
    #[test]
    fn audit_checks_not_restartable() {
        assert!(!can_restart("process-audit"));
        assert!(!can_restart("port-security"));
        assert!(!can_restart("workshop-crash-loop"));
    }
}

