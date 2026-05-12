use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, SystemTime};

use crate::types::{CostBreakdown, TokenCounts};

static WARNED_MODELS: OnceLock<Mutex<HashSet<String>>> = OnceLock::new();

const LITELLM_URL: &str = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json";
const CACHE_TTL: Duration = Duration::from_secs(3600); // 1 hour

/// Per-token pricing for a model
#[derive(Debug, Clone)]
pub struct ModelPricing {
    pub input_cost_per_token: f64,
    pub output_cost_per_token: f64,
    pub cache_creation_cost_per_token: f64,
    pub cache_creation_1h_cost_per_token: f64,
    pub cache_read_cost_per_token: f64,
}

/// Pricing lookup table
pub struct PricingTable {
    models: HashMap<String, ModelPricing>,
}

impl PricingTable {
    /// Create pricing table: use cache/fallback immediately, never block on network.
    /// Spawns a background thread to refresh stale cache.
    pub fn load(offline: bool) -> Self {
        let cache_path = Self::cache_path();

        // Try to load from cache (any age)
        if let Some(table) = Self::try_load_cache(&cache_path) {
            // If stale, refresh in background
            if !offline {
                if let Ok(meta) = std::fs::metadata(&cache_path) {
                    if let Ok(mtime) = meta.modified() {
                        if SystemTime::now().duration_since(mtime).unwrap_or(CACHE_TTL) >= CACHE_TTL
                        {
                            std::thread::spawn(move || {
                                let _ = Self::fetch_and_cache(&cache_path);
                            });
                        }
                    }
                }
            }
            return table;
        }

        // No cache at all: try a quick fetch (with short timeout)
        if !offline {
            if let Some(table) = Self::fetch_and_cache(&cache_path) {
                return table;
            }
        }

        Self::fallback()
    }

    fn try_load_cache(cache_path: &PathBuf) -> Option<Self> {
        let data = std::fs::read_to_string(cache_path).ok()?;
        let json: Value = serde_json::from_str(&data).ok()?;
        Some(Self::from_litellm_json(&json))
    }

    fn fetch_and_cache(cache_path: &PathBuf) -> Option<Self> {
        // Ensure cache directory exists
        if let Some(parent) = cache_path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }

        // Use curl (much faster on macOS than reqwest's default TLS stack)
        let output = std::process::Command::new("curl")
            .args(["-sL", "--max-time", "5", LITELLM_URL])
            .output()
            .ok()?;

        if !output.status.success() {
            return None;
        }

        let text = String::from_utf8(output.stdout).ok()?;
        let json: Value = serde_json::from_str(&text).ok()?;

        let _ = std::fs::write(cache_path, &text);

        Some(Self::from_litellm_json(&json))
    }

    fn from_litellm_json(json: &Value) -> Self {
        let mut models = HashMap::new();

        if let Some(obj) = json.as_object() {
            for (key, val) in obj {
                // Skip the "sample_spec" key
                if key == "sample_spec" {
                    continue;
                }

                let input = val
                    .get("input_cost_per_token")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0);
                let output = val
                    .get("output_cost_per_token")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0);

                // Skip entries with no pricing
                if input == 0.0 && output == 0.0 {
                    continue;
                }

                let cache_creation = val
                    .get("cache_creation_input_token_cost")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0);
                let cache_creation_1h = val
                    .get("cache_creation_input_token_cost_above_1hr")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(cache_creation);
                let cache_read = val
                    .get("cache_read_input_token_cost")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0);

                models.insert(
                    key.clone(),
                    ModelPricing {
                        input_cost_per_token: input,
                        output_cost_per_token: output,
                        cache_creation_cost_per_token: cache_creation,
                        cache_creation_1h_cost_per_token: cache_creation_1h,
                        cache_read_cost_per_token: cache_read,
                    },
                );
            }
        }

        Self { models }
    }

    /// Hardcoded fallback pricing (per token)
    fn fallback() -> Self {
        let mut models = HashMap::new();

        // Claude Opus 4.6: $5/MTok input, $25/MTok output
        let opus = ModelPricing {
            input_cost_per_token: 5.0 / 1_000_000.0,
            output_cost_per_token: 25.0 / 1_000_000.0,
            cache_creation_cost_per_token: 6.25 / 1_000_000.0,
            cache_creation_1h_cost_per_token: 10.0 / 1_000_000.0,
            cache_read_cost_per_token: 0.50 / 1_000_000.0,
        };
        models.insert("claude-opus-4-6".to_string(), opus.clone());

        // Claude Sonnet 4.6: $3/MTok input, $15/MTok output
        let sonnet = ModelPricing {
            input_cost_per_token: 3.0 / 1_000_000.0,
            output_cost_per_token: 15.0 / 1_000_000.0,
            cache_creation_cost_per_token: 3.75 / 1_000_000.0,
            cache_creation_1h_cost_per_token: 6.0 / 1_000_000.0,
            cache_read_cost_per_token: 0.30 / 1_000_000.0,
        };
        models.insert("claude-sonnet-4-6".to_string(), sonnet.clone());

        // Claude Haiku 4.5: $0.80/MTok input, $4/MTok output
        let haiku = ModelPricing {
            input_cost_per_token: 0.80 / 1_000_000.0,
            output_cost_per_token: 4.0 / 1_000_000.0,
            cache_creation_cost_per_token: 1.0 / 1_000_000.0,
            cache_creation_1h_cost_per_token: 1.25 / 1_000_000.0,
            cache_read_cost_per_token: 0.08 / 1_000_000.0,
        };
        models.insert("claude-haiku-4-5-20251001".to_string(), haiku.clone());

        Self { models }
    }

    /// Look up pricing for a model.
    /// Priority: exact → anthropic/ prefix → fuzzy (excluding bedrock/vertex_ai entries)
    pub fn get(&self, model: &str) -> Option<&ModelPricing> {
        // 1. Exact match
        if let Some(p) = self.models.get(model) {
            return Some(p);
        }

        // 2. Try with "anthropic/" prefix (LiteLLM convention)
        let with_prefix = format!("anthropic/{}", model);
        if let Some(p) = self.models.get(&with_prefix) {
            return Some(p);
        }

        // 3. Fuzzy match: skip bedrock/vertex_ai entries to avoid wrong tiered pricing
        let mut best_match: Option<(&str, &ModelPricing)> = None;
        for (key, pricing) in &self.models {
            // Skip provider-specific entries that have different pricing
            if key.starts_with("bedrock/")
                || key.starts_with("vertex_ai/")
                || key.starts_with("azure/")
            {
                continue;
            }

            if key.contains(model) || model.contains(key.as_str()) {
                match best_match {
                    None => best_match = Some((key, pricing)),
                    Some((prev_key, _)) if key.len() > prev_key.len() => {
                        best_match = Some((key, pricing));
                    }
                    _ => {}
                }
            }
        }

        best_match.map(|(_, p)| p)
    }

    /// Calculate cost for given token counts, model, and optional speed mode.
    /// When speed is "fast", output cost is multiplied by 6x.
    pub fn calculate_cost(
        &self,
        model: &str,
        tokens: &TokenCounts,
        speed: Option<&str>,
    ) -> CostBreakdown {
        match self.get(model) {
            Some(pricing) => {
                let output_multiplier = if speed == Some("fast") { 6.0 } else { 1.0 };
                CostBreakdown {
                    input_cost: tokens.input_tokens as f64 * pricing.input_cost_per_token,
                    output_cost: tokens.output_tokens as f64
                        * pricing.output_cost_per_token
                        * output_multiplier,
                    cache_creation_cost: tokens.cache_creation_5m_tokens as f64
                        * pricing.cache_creation_cost_per_token
                        + tokens.cache_creation_1h_tokens as f64
                            * pricing.cache_creation_1h_cost_per_token,
                    cache_read_cost: tokens.cache_read_tokens as f64
                        * pricing.cache_read_cost_per_token,
                    thinking_cost: tokens.thinking_tokens as f64
                        * pricing.output_cost_per_token
                        * output_multiplier,
                }
            }
            None => {
                let warned = WARNED_MODELS.get_or_init(|| Mutex::new(HashSet::new()));
                if let Ok(mut set) = warned.lock() {
                    if set.insert(model.to_string()) {
                        eprintln!("warning: unknown model \"{}\", cost will be $0", model);
                    }
                }
                CostBreakdown::default()
            }
        }
    }

    fn cache_path() -> PathBuf {
        dirs::cache_dir()
            .unwrap_or_else(|| PathBuf::from("/tmp"))
            .join("ccusage-rs")
            .join("pricing.json")
    }
}
