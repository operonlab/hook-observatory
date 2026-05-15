//! Service config loaded from `config.yaml` + env overrides.

use figment::{
    providers::{Env, Format, Yaml},
    Figment,
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    #[serde(default = "default_host")]
    pub host: String,
    #[serde(default = "default_port")]
    pub port: u16,
    /// Default frames-per-second when the request omits it.
    #[serde(default = "default_fps")]
    pub default_fps: u32,
    /// Default viewport (width, height).
    #[serde(default = "default_viewport")]
    pub default_viewport: [u32; 2],
    /// Path to chromium binary. Empty → auto-detect via `flags::find_chrome`.
    #[serde(default)]
    pub chromium_path: String,
}

fn default_host() -> String { "127.0.0.1".into() }
fn default_port() -> u16 { 10221 }
fn default_fps() -> u32 { 30 }
fn default_viewport() -> [u32; 2] { [1920, 1080] }

impl Config {
    pub fn load(path: &str) -> anyhow::Result<Self> {
        let figment = Figment::new()
            .merge(Yaml::file(path))
            .merge(Env::prefixed("BROWSER_RENDER_"));
        Ok(figment.extract()?)
    }
}
