use std::time::Duration;
use tokio::process::Command;
use tokio::time::timeout;

pub fn applicable(service: &str) -> bool {
    service.starts_with("frontend")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frontend_services_applicable() {
        assert!(applicable("frontend"));
        assert!(applicable("frontend-finance"));
        assert!(applicable("frontend-memvault"));
    }

    #[test]
    fn backend_services_not_applicable() {
        assert!(!applicable("core"));
        assert!(!applicable("blog"));
        assert!(!applicable("paper"));
    }
}


pub async fn rebuild() -> anyhow::Result<()> {
    let workbench = "/Users/joneshong/workshop/workbench";
    let pnpm = "/opt/homebrew/opt/node@22/lib/node_modules/corepack/shims/pnpm";

    let out = timeout(
        Duration::from_secs(300),
        Command::new(pnpm)
            .args(["run", "build"])
            .current_dir(workbench)
            .output(),
    )
    .await
    .map_err(|_| anyhow::anyhow!("pnpm build timed out"))??;

    if !out.status.success() {
        return Err(anyhow::anyhow!(
            "pnpm build failed: {}",
            String::from_utf8_lossy(&out.stderr)
        ));
    }

    // Nginx reload for picking up new dist/
    let _ = Command::new("/opt/homebrew/bin/nginx")
        .args(["-s", "reload"])
        .output()
        .await;

    Ok(())
}
