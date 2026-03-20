use chrono::{DateTime, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Raw usage data extracted from a single JSONL assistant entry
#[derive(Debug, Clone)]
pub struct UsageEntry {
    pub timestamp: DateTime<Utc>,
    pub session_id: String,
    pub model: String,
    pub cwd: Option<String>,
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub cache_creation_tokens: u64,
    pub cache_read_tokens: u64,
}

/// Aggregated token counts
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TokenCounts {
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub cache_creation_tokens: u64,
    pub cache_read_tokens: u64,
}

impl TokenCounts {
    pub fn total_tokens(&self) -> u64 {
        self.input_tokens + self.output_tokens + self.cache_creation_tokens + self.cache_read_tokens
    }

    pub fn merge(&mut self, other: &TokenCounts) {
        self.input_tokens += other.input_tokens;
        self.output_tokens += other.output_tokens;
        self.cache_creation_tokens += other.cache_creation_tokens;
        self.cache_read_tokens += other.cache_read_tokens;
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
    pub total_tokens: TokenCounts,
    pub total_cost: f64,
    pub by_model: HashMap<String, ModelUsage>,
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

/// Aggregation result container
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum AggregationResult {
    Daily(Vec<DailySummary>),
    Monthly(Vec<MonthlySummary>),
    Weekly(Vec<WeeklySummary>),
    Session(Vec<SessionUsage>),
    Blocks(Vec<BlockSummary>),
}

/// Metadata about a scanned JSONL file
#[derive(Debug, Clone)]
pub struct FileInfo {
    pub path: std::path::PathBuf,
    pub mtime: std::time::SystemTime,
    #[allow(dead_code)]
    pub project: String,
}
