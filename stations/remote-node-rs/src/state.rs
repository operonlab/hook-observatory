use crate::config::Config;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::RwLock;

#[derive(Debug, Clone, Default)]
pub struct RemoteHealth {
    pub healthy: bool,
    pub last_check: f64,
    pub last_error: String,
}

#[derive(Clone)]
pub struct AppState {
    pub cfg: Config,
    pub http: reqwest::Client,
    pub health: Arc<RwLock<RemoteHealth>>,
    pub output_dir: PathBuf,
}

impl AppState {
    pub fn new(cfg: Config) -> anyhow::Result<Self> {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(cfg.timeout))
            .build()?;
        let output_dir = cfg.output_dir_resolved();
        std::fs::create_dir_all(&output_dir)?;
        Ok(Self {
            cfg,
            http,
            health: Arc::new(RwLock::new(RemoteHealth::default())),
            output_dir,
        })
    }
}
