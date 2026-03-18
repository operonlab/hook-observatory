use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RlmConfig {
    pub model: String,
    pub sub_model: String,
    pub max_depth: u32,
    pub max_iterations: u32,
    pub max_timeout_secs: f64,
    pub max_errors: u32,
    pub compaction: bool,
    pub compaction_threshold: usize,
    pub repl_output_limit: usize,
    pub verbose: bool,
    pub api_base: Option<String>,
    pub api_key: Option<String>,
}

impl Default for RlmConfig {
    fn default() -> Self {
        Self {
            model: "sonnet".into(),
            sub_model: "haiku".into(),
            max_depth: 2,
            max_iterations: 20,
            max_timeout_secs: 300.0,
            max_errors: 5,
            compaction: true,
            compaction_threshold: 60_000,
            repl_output_limit: 20_000,
            verbose: false,
            api_base: None,
            api_key: None,
        }
    }
}

#[derive(Debug, Default, Serialize)]
pub struct RlmUsage {
    pub total_calls: u32,
    pub total_time_secs: f64,
}

#[derive(Debug, Serialize)]
pub struct RlmResult {
    pub response: String,
    pub usage: RlmUsage,
    pub iterations: u32,
    pub depth: u32,
    pub execution_time_secs: f64,
    pub trajectory: Vec<TrajectoryEntry>,
    pub status: String,
}

#[derive(Debug, Serialize)]
pub struct TrajectoryEntry {
    pub iteration: u32,
    pub action: String,
    pub code_blocks: Option<usize>,
    pub response_preview: Option<String>,
}

/// Context passed to the RLM engine.
#[derive(Debug, Clone)]
pub enum Context {
    Single(String),
    Chunks(Vec<String>),
}

impl Context {
    pub fn metadata(&self) -> String {
        match self {
            Context::Single(s) => format!("Context: string, {} chars", s.len()),
            Context::Chunks(chunks) => {
                let total: usize = chunks.iter().map(|c| c.len()).sum();
                let n = chunks.len();
                let lengths: Vec<usize> = chunks.iter().take(20).map(|c| c.len()).collect();
                let extra = if n > 20 {
                    format!("... [{} more]", n - 20)
                } else {
                    String::new()
                };
                format!(
                    "Context: list of {} chunks, total {} chars, lengths: {:?}{}",
                    n, total, lengths, extra
                )
            }
        }
    }
}
