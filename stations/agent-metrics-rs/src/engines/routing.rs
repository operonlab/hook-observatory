//! Routing — task analysis, pattern selection, CLI/tier routing.
//!
//! Faithful Rust port of the analysis half of `agent_metrics.engines.maestro`.

use crate::config::Settings;
use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};
use serde_yaml::Value;
use std::collections::BTreeMap;
use std::sync::Mutex;

#[derive(Debug, Clone, Serialize)]
pub struct TaskAnalysis {
    pub description: String,
    pub complexity: String,         // simple | moderate | complex
    pub decomposability: String,    // atomic | sequential | parallel
    pub categories: Vec<String>,
    pub recommended_pattern: String, // solo | pipeline | race | swarm | escalation
    pub recommended_tier: String,    // headless | relay | fleet
    pub phases: Vec<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub explicit_clis: Option<Vec<String>>,
}

impl TaskAnalysis {
    fn new(description: &str) -> Self {
        Self {
            description: description.to_string(),
            complexity: "simple".into(),
            decomposability: "atomic".into(),
            categories: Vec::new(),
            recommended_pattern: "solo".into(),
            recommended_tier: "headless".into(),
            phases: Vec::new(),
            explicit_clis: None,
        }
    }
}

// ── Routing table loader (cached) ───────────────────────────────

static ROUTING_CACHE: Lazy<Mutex<Option<Value>>> = Lazy::new(|| Mutex::new(None));

fn load_routing_table(settings: &Settings) -> Value {
    {
        let cache = ROUTING_CACHE.lock().unwrap();
        if let Some(v) = cache.as_ref() {
            return v.clone();
        }
    }
    let path = std::path::Path::new(&settings.routing_table_path);
    let parsed = std::fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_yaml::from_str::<Value>(&s).ok())
        .unwrap_or(Value::Null);
    let mut cache = ROUTING_CACHE.lock().unwrap();
    *cache = Some(parsed.clone());
    parsed
}

pub fn get_cli_routing(settings: &Settings) -> BTreeMap<String, BTreeMap<String, String>> {
    let table = load_routing_table(settings);
    let mut out = BTreeMap::new();
    if let Some(map) = table.get("cli_routing").and_then(|v| v.as_mapping()) {
        for (k, v) in map {
            let key = k.as_str().unwrap_or_default().to_string();
            let mut inner = BTreeMap::new();
            if let Some(inner_map) = v.as_mapping() {
                for (kk, vv) in inner_map {
                    if let (Some(ks), Some(vs)) = (kk.as_str(), vv.as_str()) {
                        inner.insert(ks.to_string(), vs.to_string());
                    }
                }
            }
            out.insert(key, inner);
        }
    }
    out
}

pub fn get_pipeline_templates(settings: &Settings) -> BTreeMap<String, Vec<Value>> {
    let table = load_routing_table(settings);
    let mut out = BTreeMap::new();
    if let Some(map) = table.get("pipeline_templates").and_then(|v| v.as_mapping()) {
        for (k, v) in map {
            let key = k.as_str().unwrap_or_default().to_string();
            // Convert serde_yaml::Sequence into Vec<Value> (still YAML; serialize as JSON when emitting)
            if let Some(seq) = v.as_sequence() {
                out.insert(key, seq.clone());
            } else {
                out.insert(key, vec![]);
            }
        }
    }
    out
}

pub fn get_category_keywords(settings: &Settings) -> BTreeMap<String, Vec<String>> {
    let table = load_routing_table(settings);
    let mut out = BTreeMap::new();
    if let Some(map) = table.get("category_keywords").and_then(|v| v.as_mapping()) {
        for (k, v) in map {
            let key = k.as_str().unwrap_or_default().to_string();
            let kws = v
                .as_sequence()
                .map(|s| s.iter().filter_map(|x| x.as_str().map(String::from)).collect())
                .unwrap_or_default();
            out.insert(key, kws);
        }
    }
    out
}

pub fn get_tier_routing(settings: &Settings) -> Value {
    load_routing_table(settings)
        .get("tier_routing")
        .cloned()
        .unwrap_or(Value::Null)
}

pub fn get_tier_keywords(settings: &Settings) -> BTreeMap<String, Vec<String>> {
    let table = load_routing_table(settings);
    let mut out = BTreeMap::new();
    if let Some(map) = table.get("tier_keywords").and_then(|v| v.as_mapping()) {
        for (k, v) in map {
            let key = k.as_str().unwrap_or_default().to_string();
            let kws = v
                .as_sequence()
                .map(|s| s.iter().filter_map(|x| x.as_str().map(String::from)).collect())
                .unwrap_or_default();
            out.insert(key, kws);
        }
    }
    out
}

// ── CLI alias detection ─────────────────────────────────────────

const CLI_ALIASES: &[(&str, &str)] = &[
    ("claude", "claude"),
    ("claude code", "claude"),
    ("claude-code", "claude"),
    ("codex", "codex"),
    ("codex cli", "codex"),
    ("codex-cli", "codex"),
    ("openai codex", "codex"),
    ("openai", "codex"),
    ("gemini", "gemini"),
    ("gemini cli", "gemini"),
    ("gemini-cli", "gemini"),
    ("google gemini", "gemini"),
];

pub fn detect_explicit_clis(description: &str) -> Vec<String> {
    let desc_lower = description.to_lowercase();
    let mut found: BTreeMap<String, usize> = BTreeMap::new();
    let mut aliases: Vec<&(&str, &str)> = CLI_ALIASES.iter().collect();
    aliases.sort_by_key(|(a, _)| std::cmp::Reverse(a.len()));
    for (alias, canon) in aliases {
        if let Some(pos) = desc_lower.find(alias) {
            found.entry((*canon).into()).or_insert(pos);
        }
    }
    let mut sorted: Vec<(String, usize)> = found.into_iter().collect();
    sorted.sort_by_key(|(_, p)| *p);
    sorted.into_iter().map(|(c, _)| c).collect()
}

// ── Text classification ─────────────────────────────────────────

fn is_cjk(text: &str) -> bool {
    text.chars().any(|c| {
        let n = c as u32;
        (0x4E00..=0x9FFF).contains(&n) || (0x3400..=0x4DBF).contains(&n)
    })
}

fn count_cjk(text: &str) -> usize {
    text.chars()
        .filter(|c| {
            let n = *c as u32;
            (0x4E00..=0x9FFF).contains(&n) || (0x3400..=0x4DBF).contains(&n)
        })
        .count()
}

/// Word-boundary match: Latin words use \b, CJK falls back to substring.
fn word_match(pattern: &str, text: &str) -> bool {
    if is_cjk(pattern) {
        return text.contains(pattern);
    }
    let p = pattern.to_lowercase();
    let t = text.to_lowercase();
    // Walk the text looking for `pattern` flanked by non-word chars (or string ends).
    let bytes = t.as_bytes();
    let pat = p.as_bytes();
    if pat.is_empty() {
        return false;
    }
    let mut i = 0;
    while i + pat.len() <= bytes.len() {
        if &bytes[i..i + pat.len()] == pat {
            let prev_ok = i == 0 || !is_word_byte(bytes[i - 1]);
            let next_idx = i + pat.len();
            let next_ok = next_idx == bytes.len() || !is_word_byte(bytes[next_idx]);
            if prev_ok && next_ok {
                return true;
            }
        }
        i += 1;
    }
    false
}

fn is_word_byte(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'_'
}

fn effective_word_count(description: &str) -> usize {
    let words = description.split_whitespace().count();
    let cjk = count_cjk(description);
    if cjk > 5 {
        words + cjk / 2
    } else {
        words
    }
}

const MULTI_SIGNAL_WORDS: &[&str] = &[
    "and", "then", "also", "plus", "with", "including",
    "並且", "然後", "還有", "以及", "同時",
];

const SEQ_SIGNAL_WORDS: &[&str] = &[
    "first", "then", "after that", "finally", "step 1", "phase",
];

const SEQ_CJK_WORDS: &[&str] = &["先", "然後", "接著", "最後"];

pub fn analyze_task(settings: &Settings, description: &str, budget: &str) -> TaskAnalysis {
    let desc_lower = description.to_lowercase();
    let mut analysis = TaskAnalysis::new(description);
    let keywords = get_category_keywords(settings);

    let mut scores: BTreeMap<String, i64> = BTreeMap::new();
    for (cat, kw_list) in &keywords {
        let mut score: i64 = 0;
        for kw in kw_list {
            if word_match(kw, &desc_lower) {
                score += 1;
            }
        }
        if score > 0 {
            scores.insert(cat.clone(), score);
        }
    }
    if scores.is_empty() {
        analysis.categories = vec!["code_generation".into()];
    } else {
        let mut pairs: Vec<(String, i64)> = scores.into_iter().collect();
        pairs.sort_by(|a, b| b.1.cmp(&a.1));
        analysis.categories = pairs.into_iter().map(|(k, _)| k).collect();
    }

    let word_count = effective_word_count(description);
    let mut multi_signals: i64 = 0;
    for w in MULTI_SIGNAL_WORDS {
        if is_cjk(w) {
            multi_signals += desc_lower.matches(w).count() as i64;
        } else if word_match(w, &desc_lower) {
            // word_match returns boolean; count actual occurrences via repeated search
            let mut idx = 0usize;
            let lw = desc_lower.as_str();
            while let Some(pos) = lw[idx..].find(*w) {
                let abs = idx + pos;
                let prev_ok = abs == 0 || !is_word_byte(lw.as_bytes()[abs - 1]);
                let next = abs + w.len();
                let next_ok = next == lw.len() || !is_word_byte(lw.as_bytes()[next]);
                if prev_ok && next_ok {
                    multi_signals += 1;
                }
                idx = abs + w.len();
            }
        }
    }

    if word_count > 30 || multi_signals >= 2 {
        analysis.complexity = "complex".into();
    } else if word_count > 12 || multi_signals >= 1 {
        analysis.complexity = "moderate".into();
    }

    let seq_signals = SEQ_SIGNAL_WORDS.iter().any(|p| word_match(p, &desc_lower))
        || SEQ_CJK_WORDS.iter().any(|p| desc_lower.contains(p));
    let par_signals =
        desc_lower.matches(" and ").count() >= 2 || desc_lower.matches('、').count() >= 2;

    if seq_signals {
        analysis.decomposability = "sequential".into();
    } else if par_signals && analysis.complexity != "simple" {
        analysis.decomposability = "parallel".into();
    } else if analysis.categories.len() >= 2 && analysis.complexity == "complex" {
        analysis.decomposability = "parallel".into();
    }

    analysis.recommended_pattern = select_pattern(&analysis, budget);

    if analysis.recommended_pattern == "pipeline" {
        let primary = analysis.categories.first().cloned().unwrap_or_else(|| "code_generation".into());
        let templates = get_pipeline_templates(settings);
        analysis.phases = templates
            .get(&primary)
            .or_else(|| templates.get("code_generation"))
            .cloned()
            .unwrap_or_default();
    }
    analysis
}

pub fn select_pattern(analysis: &TaskAnalysis, budget: &str) -> String {
    if budget == "minimize" {
        return "escalation".into();
    }
    if analysis.decomposability == "sequential" {
        return "pipeline".into();
    }
    if analysis.decomposability == "parallel"
        && (analysis.complexity == "complex" || analysis.complexity == "moderate")
    {
        return "swarm".into();
    }
    "solo".into()
}

pub fn route_to_cli(settings: &Settings, category: &str, budget: &str) -> String {
    let tier = match budget {
        "minimize" => "budget",
        "maximize_quality" => "power",
        _ => "primary",
    };
    let routing = get_cli_routing(settings);
    let cat = routing
        .get(category)
        .or_else(|| routing.get("code_generation"))
        .cloned()
        .unwrap_or_default();
    cat.get(tier).cloned().unwrap_or_else(|| "claude".into())
}

// ── Tier selection ──────────────────────────────────────────────

pub fn select_tier(
    settings: &Settings,
    analysis: &TaskAnalysis,
    tier_override: Option<&str>,
) -> String {
    if let Some(t) = tier_override {
        if matches!(t, "headless" | "relay" | "fleet") {
            return t.to_string();
        }
    }
    let tier_kw = get_tier_keywords(settings);
    let task_lower = analysis.description.to_lowercase();
    let routing = get_tier_routing(settings);
    if let Some(signals) = routing.get("signals").and_then(|v| v.as_mapping()) {
        for (signal, tier) in signals {
            let s = signal.as_str().unwrap_or_default();
            let t = tier.as_str().unwrap_or_default();
            if let Some(kws) = tier_kw.get(s) {
                if kws.iter().any(|kw| task_lower.contains(&kw.to_lowercase())) {
                    return t.to_string();
                }
            }
        }
    }
    let defaults = routing.get("defaults").and_then(|v| v.as_mapping());
    let primary = analysis.categories.first().cloned().unwrap_or_else(|| "code_generation".into());
    if let Some(defs) = defaults {
        for (k, v) in defs {
            if k.as_str() == Some(&primary) {
                if let Some(t) = v.as_str() {
                    return t.to_string();
                }
            }
        }
    }
    "headless".into()
}

pub fn tier_fallback_chain(settings: &Settings, tier: &str) -> Vec<String> {
    let routing = get_tier_routing(settings);
    routing
        .get("fallback")
        .and_then(|v| v.as_mapping())
        .and_then(|m| {
            m.iter().find_map(|(k, v)| {
                if k.as_str() == Some(tier) {
                    v.as_sequence().map(|seq| {
                        seq.iter()
                            .filter_map(|x| x.as_str().map(String::from))
                            .collect()
                    })
                } else {
                    None
                }
            })
        })
        .unwrap_or_default()
}

pub async fn check_tier_available(tier: &str, _settings: &Settings) -> bool {
    if tier == "headless" {
        return true;
    }
    let url = match tier {
        "relay" => std::env::var("AGENT_METRICS_RELAY_URL")
            .unwrap_or_else(|_| crate::config::yaml_url("hook-observatory", "/health", 10100)),
        // TODO: port 10209 not in port_registry.yaml — see dispatch.rs note.
        "fleet" => std::env::var("AGENT_METRICS_FLEET_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:10209/health".into()),
        _ => return false,
    };
    let client = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };
    client
        .get(&url)
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}

pub async fn resolve_tier(
    settings: &Settings,
    analysis: &TaskAnalysis,
    tier_override: Option<&str>,
) -> String {
    let preferred = select_tier(settings, analysis, tier_override);
    if check_tier_available(&preferred, settings).await {
        return preferred;
    }
    for fallback in tier_fallback_chain(settings, &preferred) {
        if check_tier_available(&fallback, settings).await {
            tracing::warn!(preferred = %preferred, fallback = %fallback, "tier_fallback");
            return fallback;
        }
    }
    "headless".into()
}

// ── Pure helpers ────────────────────────────────────────────────

pub fn quality_check(output: &str) -> bool {
    let trimmed = output.trim();
    if trimmed.len() < 50 {
        return false;
    }
    let lower = trimmed.to_lowercase();
    let signals = ["error:", "traceback", "exception", "failed", "could not"];
    !signals.iter().any(|s| lower.contains(s))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cli_aliases_detected_in_order_of_appearance() {
        let v = detect_explicit_clis("First use Codex then Gemini, finally Claude.");
        assert_eq!(v, vec!["codex".to_string(), "gemini".into(), "claude".into()]);
    }

    #[test]
    fn cjk_substring_match_skips_word_boundary() {
        assert!(word_match("重構", "全面重構這個模組"));
        assert!(!word_match("重構", "完全不相關"));
    }

    #[test]
    fn ascii_match_respects_word_boundary() {
        assert!(word_match("test", "run the test now"));
        assert!(!word_match("test", "testing should not match"));
    }

    #[test]
    fn quality_check_short_output_fails() {
        assert!(!quality_check("hi"));
        assert!(quality_check(&"x".repeat(100)));
        assert!(!quality_check("Traceback (most recent call last):\n  File ..."));
    }

    #[test]
    fn select_pattern_minimize_escalation() {
        let a = TaskAnalysis::new("trivial");
        assert_eq!(select_pattern(&a, "minimize"), "escalation");
    }

    #[test]
    fn select_pattern_sequential_pipeline() {
        let mut a = TaskAnalysis::new("first do A then B");
        a.decomposability = "sequential".into();
        assert_eq!(select_pattern(&a, "balanced"), "pipeline");
    }
}
