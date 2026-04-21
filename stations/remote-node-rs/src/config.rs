use serde::Deserialize;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    #[serde(default = "default_port")]
    pub port: u16,
    #[serde(default = "default_host")]
    pub host: String,
    #[serde(default = "default_remote_url")]
    pub remote_url: String,
    #[serde(default = "default_health_interval")]
    pub health_interval: u64,
    #[serde(default = "default_timeout")]
    pub timeout: u64,
    #[serde(default = "default_output_dir")]
    pub output_dir: String,
}

fn default_port() -> u16 { 10208 }
fn default_host() -> String { "127.0.0.1".to_string() }
fn default_remote_url() -> String { "http://win-gpu:7860".to_string() }
fn default_health_interval() -> u64 { 30 }
fn default_timeout() -> u64 { 120 }
fn default_output_dir() -> String { "~/workshop/outputs/remote-node".to_string() }

impl Default for Config {
    fn default() -> Self {
        Self {
            port: default_port(),
            host: default_host(),
            remote_url: default_remote_url(),
            health_interval: default_health_interval(),
            timeout: default_timeout(),
            output_dir: default_output_dir(),
        }
    }
}

impl Config {
    pub fn load(path: &Path) -> anyhow::Result<Self> {
        if !path.exists() {
            return Ok(Self::default());
        }
        let text = std::fs::read_to_string(path)?;
        let cfg: Config = serde_yaml::from_str(&text)?;
        Ok(cfg.normalized())
    }

    pub fn normalized(mut self) -> Self {
        self.remote_url = self.remote_url.trim_end_matches('/').to_string();
        self
    }

    pub fn output_dir_resolved(&self) -> PathBuf {
        PathBuf::from(shellexpand::tilde(&self.output_dir).into_owned())
    }
}
