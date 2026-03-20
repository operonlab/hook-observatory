use chrono::{DateTime, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Output configuration flags
#[derive(Debug, Clone, Default)]
pub struct OutputConfig {
    pub no_cost: bool,
    pub no_color: bool,
    pub csv: bool,
    pub limit: Option<usize>,
    #[allow(dead_code)]
    pub order_desc: bool,
}

/// Instance (project) usage summary
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstanceUsage {
    pub project: String,
    pub session_count: usize,
    pub total_tokens: TokenCounts,
    pub total_cost: f64,
    pub by_model: HashMap<String, ModelUsage>,
}

/// Raw usage data extracted from a single JSONL assistant entry
#[derive(Debug, Clone)]
pub struct UsageEntry {
    pub timestamp: DateTime<Utc>,
    pub session_id: String,
    pub message_id: Option<String>,
    pub model: String,
    pub cwd: Option<String>,
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub cache_creation_5m_tokens: u64,
    pub cache_creation_1h_tokens: u64,
    pub cache_read_tokens: u64,
    pub thinking_tokens: u64,
    pub speed: Option<String>,
    pub slug: Option<String>,
    pub agent_id: Option<String>,
}

/// Aggregated token counts
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TokenCounts {
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub cache_creation_5m_tokens: u64,
    pub cache_creation_1h_tokens: u64,
    pub cache_read_tokens: u64,
    pub thinking_tokens: u64,
}

impl TokenCounts {
    /// Combined cache creation tokens (5m + 1h) for display
    pub fn cache_creation_tokens(&self) -> u64 {
        self.cache_creation_5m_tokens + self.cache_creation_1h_tokens
    }

    pub fn total_tokens(&self) -> u64 {
        self.input_tokens + self.output_tokens + self.cache_creation_tokens() + self.cache_read_tokens + self.thinking_tokens
    }

    pub fn merge(&mut self, other: &TokenCounts) {
        self.input_tokens += other.input_tokens;
        self.output_tokens += other.output_tokens;
        self.cache_creation_5m_tokens += other.cache_creation_5m_tokens;
        self.cache_creation_1h_tokens += other.cache_creation_1h_tokens;
        self.cache_read_tokens += other.cache_read_tokens;
        self.thinking_tokens += other.thinking_tokens;
    }
}

/// Cost breakdown for a model
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CostBreakdown {
    pub input_cost: f64,
    pub output_cost: f64,
    pub cache_creation_cost: f64,
    pub cache_read_cost: f64,
}

impl CostBreakdown {
    pub fn total(&self) -> f64 {
        self.input_cost + self.output_cost + self.cache_creation_cost + self.cache_read_cost
    }

    pub fn merge(&mut self, other: &CostBreakdown) {
        self.input_cost += other.input_cost;
        self.output_cost += other.output_cost;
        self.cache_creation_cost += other.cache_creation_cost;
        self.cache_read_cost += other.cache_read_cost;
    }
}

/// Per-model usage summary
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ModelUsage {
    pub tokens: TokenCounts,
    pub cost: CostBreakdown,
}

/// Daily aggregated summary
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DailySummary {
    pub date: NaiveDate,
    pub total_tokens: TokenCounts,
    pub total_cost: f64,
    pub by_model: HashMap<String, ModelUsage>,
}

/// Monthly aggregated summary
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MonthlySummary {
    pub year: i32,
    pub month: u32,
    pub total_tokens: TokenCounts,
    pub total_cost: f64,
    pub by_model: HashMap<String, ModelUsage>,
}

/// Weekly aggregated summary
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WeeklySummary {
    pub week_start: NaiveDate,
    pub week_end: NaiveDate,
    pub total_tokens: TokenCounts,
    pub total_cost: f64,
    pub by_model: HashMap<String, ModelUsage>,
}

/// Session usage summary
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionUsage {
    pub session_id: String,
    pub date: NaiveDate,
    pub project: Option<String>,
    #[serde(default)]
    pub slug: Option<String>,
    pub total_tokens: TokenCounts,
    pub total_cost: f64,
    pub by_model: HashMap<String, ModelUsage>,
    pub first_activity: Option<DateTime<Utc>>,
    pub last_activity: Option<DateTime<Utc>>,
    #[serde(default)]
    pub fast_entry_count: usize,
}

/// 5-hour billing block summary
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BlockSummary {
    pub block_start: DateTime<Utc>,
    pub block_end: DateTime<Utc>,
    pub total_tokens: TokenCounts,
    pub total_cost: f64,
    pub by_model: HashMap<String, ModelUsage>,
}

/// Per-agent usage within a session
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentUsage {
    pub agent_id: Option<String>,
    pub model: Option<String>,
    pub tokens: TokenCounts,
    pub cost: f64,
    pub cost_pct: f64,
    pub entry_count: usize,
    pub by_model: HashMap<String, ModelUsage>,
}

/// Session-level agent summary
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionAgentSummary {
    pub session_id: String,
    pub slug: Option<String>,
    pub project: Option<String>,
    pub total_cost: f64,
    pub main_cost: f64,
    pub main_pct: f64,
    pub agents: Vec<AgentUsage>,
}

/// Aggregation result container
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum AggregationResult {
    Daily(Vec<DailySummary>),
    Monthly(Vec<MonthlySummary>),
    Weekly(Vec<WeeklySummary>),
    Session(Vec<SessionUsage>),
    Blocks(Vec<BlockSummary>),
    Instances(Vec<InstanceUsage>),
    Agents(Vec<SessionAgentSummary>),
}

/// Metadata about a scanned JSONL file
#[derive(Debug, Clone)]
pub struct FileInfo {
    pub path: std::path::PathBuf,
    pub mtime: std::time::SystemTime,
    #[allow(dead_code)]
    pub project: String,
}
