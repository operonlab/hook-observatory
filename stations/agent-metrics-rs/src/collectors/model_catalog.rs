//! Model catalog full sync — port of `schedules/runners/ws_model_catalog_sync.py`.
//!
//! Cronicle invokes `agent-metrics-rs model-catalog-sync` weekly (Mon 19:00).
//! Steps:
//!   1. Parse LiteLLM config (~/.config/litellm/config.yaml) for configured
//!      providers + Smart/Fast/Value annotations.
//!   2. Scrape 4 leaderboards (Arena, LiveBench, ArtificialAnalysis,
//!      OpenRouter) via camoufox-cli — sequential within one session.
//!   3. Borda-count merge into a consensus ranking.
//!   4. Generate 4 catalog sections (benchmark highlights, scenarios,
//!      subjective picks, notable-unconfigured).
//!   5. Write `agent-metrics:model-catalog:full` + `:notable` to Redis with
//!      8-day TTL; flock guard against concurrent runs.

use anyhow::Result;
use chrono::Utc;
use fs2::FileExt;
use redis::AsyncCommands;
use regex::Regex;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fs::{self, File};
use std::path::PathBuf;
use std::time::Duration;
use tokio::process::Command;

const REDIS_KEY: &str = "agent-metrics:model-catalog:full";
const REDIS_KEY_NOTABLE: &str = "agent-metrics:model-catalog:notable";
const REDIS_TTL_SECONDS: u64 = 86_400 * 8;
const CFX_SESSION: &str = "catalog-sync";
const FALLBACK_JSON_PATH: &str = "/tmp/agent-metrics-model-catalog-full.json";
const LOCK_FILE_PATH: &str = "/tmp/ws_model_catalog_sync.lock";

const BIG3_KEYWORDS: &[&str] = &["anthropic", "claude", "openai", "gpt", "google", "gemini"];
const PROVIDER_KEYWORDS: &[&str] =
    &["glm", "kimi", "minimax", "deepseek", "qwen", "grok", "gemini"];

// ── Leaderboard source definitions ─────────────────────────────

#[derive(Debug, Clone, Copy)]
struct LeaderboardSource {
    name: &'static str,
    url: &'static str,
    wait_s: u64,
}

const LEADERBOARD_SOURCES: &[LeaderboardSource] = &[
    LeaderboardSource {
        name: "arena",
        url: "https://lmarena.ai/?leaderboard",
        wait_s: 8,
    },
    LeaderboardSource {
        name: "livebench",
        url: "https://livebench.ai/",
        wait_s: 6,
    },
    LeaderboardSource {
        name: "artificialanalysis",
        url: "https://artificialanalysis.ai/leaderboards/models",
        wait_s: 6,
    },
    LeaderboardSource {
        name: "openrouter",
        url: "https://openrouter.ai/rankings",
        wait_s: 5,
    },
];

// ── LiteLLM config parsing ─────────────────────────────────────

#[derive(Debug, Default)]
pub struct LitellmConfig {
    pub configured_providers: BTreeSet<String>,
    pub models: Vec<ModelEntry>,
    pub annotations: HashMap<String, AnnotationSet>,
}

#[derive(Debug, Clone)]
pub struct ModelEntry {
    pub name: String,
}

#[derive(Debug, Clone)]
pub struct AnnotationSet {
    pub smart: String,
    pub fast: String,
    pub value: String,
}

fn litellm_config_path() -> PathBuf {
    let home = dirs_home();
    home.join(".config/litellm/config.yaml")
}

fn dirs_home() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/"))
}

pub fn parse_litellm_config() -> LitellmConfig {
    let path = litellm_config_path();
    let raw = match fs::read_to_string(&path) {
        Ok(s) => s,
        Err(e) => {
            tracing::warn!(path = %path.display(), error = %e, "config read failed; defaulting providers");
            let mut out = LitellmConfig::default();
            for kw in PROVIDER_KEYWORDS {
                out.configured_providers.insert((*kw).to_string());
            }
            return out;
        }
    };

    let mut out = LitellmConfig::default();

    if let Ok(yaml) = serde_yaml::from_str::<Value>(&raw) {
        if let Some(model_list) = yaml.get("model_list").and_then(|v| v.as_array()) {
            for m in model_list {
                let name = m
                    .get("model_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                if name.is_empty() {
                    continue;
                }
                let lower = name.to_lowercase();
                for kw in PROVIDER_KEYWORDS {
                    if lower.contains(kw) {
                        out.configured_providers.insert((*kw).to_string());
                    }
                }
                out.models.push(ModelEntry { name });
            }
        }
    } else {
        tracing::warn!(path = %path.display(), "config yaml parse failed; defaulting providers");
        for kw in PROVIDER_KEYWORDS {
            out.configured_providers.insert((*kw).to_string());
        }
    }

    let annot_re =
        Regex::new(r"(?i)Smart:\s*(\S+).*?Fast:\s*(\S+).*?Value:\s*(\S+)").unwrap();
    let provider_re = Regex::new(r"──\s*(\w[\w\s]*?)\s*(?:—|──)").unwrap();
    for line in raw.lines() {
        if let Some(cap) = annot_re.captures(line) {
            if let Some(pcap) = provider_re.captures(line) {
                let provider = pcap[1].trim().to_string();
                out.annotations.insert(
                    provider,
                    AnnotationSet {
                        smart: cap[1].to_string(),
                        fast: cap[2].to_string(),
                        value: cap[3].to_string(),
                    },
                );
            }
        }
    }

    out
}

// ── Camoufox helpers ───────────────────────────────────────────

async fn cfx(args: &[&str], timeout_s: u64) -> Result<std::process::Output> {
    let mut cmd = Command::new("camoufox-cli");
    cmd.arg("--session").arg(CFX_SESSION);
    for a in args {
        cmd.arg(a);
    }
    let fut = cmd.kill_on_drop(true).output();
    Ok(tokio::time::timeout(Duration::from_secs(timeout_s), fut).await??)
}

async fn cfx_close() {
    let _ = cfx(&["close"], 10).await;
}

/// Sequentially scrape all leaderboard sources within one persistent session.
pub async fn scrape_all_sources() -> BTreeMap<String, String> {
    let mut results: BTreeMap<String, String> = BTreeMap::new();
    if LEADERBOARD_SOURCES.is_empty() {
        return results;
    }

    let first = LEADERBOARD_SOURCES[0];
    let open_r = match cfx(&["--persistent", "open", first.url], 30).await {
        Ok(o) => o,
        Err(e) => {
            tracing::error!(error = %e, "cfx_open_initial_failed");
            return results;
        }
    };
    if !open_r.status.success() {
        tracing::error!(stderr = %String::from_utf8_lossy(&open_r.stderr), "cfx_open_initial_nonzero");
        cfx_close().await;
        return results;
    }
    tokio::time::sleep(Duration::from_secs(first.wait_s)).await;
    let eval_r = cfx(
        &["eval", "document.body.innerText.substring(0, 20000)"],
        20,
    )
    .await;
    if let Ok(out) = eval_r {
        if out.status.success() {
            let text = String::from_utf8_lossy(&out.stdout).trim().to_string();
            tracing::info!(name = first.name, chars = text.len(), "scraped");
            results.insert(first.name.to_string(), text);
        }
    }

    for src in LEADERBOARD_SOURCES.iter().skip(1) {
        let _ = cfx(&["open", src.url], 20).await;
        tokio::time::sleep(Duration::from_secs(src.wait_s)).await;
        let eval_r = cfx(
            &["eval", "document.body.innerText.substring(0, 20000)"],
            20,
        )
        .await;
        match eval_r {
            Ok(out) if out.status.success() => {
                let text = String::from_utf8_lossy(&out.stdout).trim().to_string();
                tracing::info!(name = src.name, chars = text.len(), "scraped");
                results.insert(src.name.to_string(), text);
            }
            _ => {
                tracing::warn!(name = src.name, "scrape failed");
            }
        }
    }

    cfx_close().await;
    results
}

// ── Score parsing ──────────────────────────────────────────────

#[derive(Debug, Clone)]
struct ScoreEntry {
    name: String,
    score: f64,
}

/// Extract (name, numeric score) pairs from leaderboard innerText.
///
/// Three patterns (in priority order):
///   1. TAB-separated row (LiveBench style):
///        "Name\tProvider\tScore\t..."  where Score is 30.0-100.0
///   2. Elo score in the line (LMSYS Arena style): 4-digit 1100-1600
///   3. Percentage suffix (legacy): "XX.X%" 30-100
fn parse_scores_from_text(text: &str) -> Vec<ScoreEntry> {
    if text.is_empty() {
        return Vec::new();
    }
    let elo_re = Regex::new(r"(\d{4})").unwrap();
    let pct_re = Regex::new(r"([\d.]+)%").unwrap();
    let mut out = Vec::new();
    for raw in text.split('\n') {
        let line = raw.trim();
        if line.is_empty() {
            continue;
        }

        // Pass 1: TAB-separated leaderboard row.
        // Modern leaderboards (LiveBench, future revamps) ship rows like
        //   "Model Name\tOrg\t80.28\t88.12\t..."
        // Score = first numeric field in [30, 100] *after* the name column.
        // Header row "Model\tOrganization\tGlobal Average\t..." is skipped
        // because no field parses as a 30-100 float.
        if line.contains('\t') {
            let parts: Vec<&str> = line.split('\t').map(str::trim).collect();
            if parts.len() >= 3 {
                let mut found = false;
                for p in parts.iter().skip(1) {
                    if let Ok(v) = p.parse::<f64>() {
                        if (30.0..=100.0).contains(&v) {
                            let name = parts[0].to_string();
                            let chars = name.chars().count();
                            // Skip footnote-only "names" (e.g. "*5th rank ...").
                            let starts_ok = name.chars().next().map_or(false, |c| {
                                c.is_alphanumeric() || c == '(' || c == '['
                            });
                            if (3..=60).contains(&chars) && starts_ok {
                                out.push(ScoreEntry { name, score: v });
                                found = true;
                            }
                            break;
                        }
                    }
                }
                if found {
                    continue;
                }
            }
        }

        // Pass 2: Elo-prefixed (Arena).
        let mut elo_hit = false;
        if let Some(m) = elo_re.find(line) {
            if let Ok(score) = m.as_str().parse::<i64>() {
                if (1100..=1600).contains(&score) {
                    let name = line[..m.start()]
                        .trim()
                        .trim_end_matches('-')
                        .trim()
                        .to_string();
                    if (3..=60).contains(&name.chars().count()) {
                        out.push(ScoreEntry {
                            name,
                            score: score as f64,
                        });
                        elo_hit = true;
                    }
                }
            }
        }
        if elo_hit {
            continue;
        }

        // Pass 3: percentage suffix (legacy).
        if let Some(m) = pct_re.find(line) {
            let s = m.as_str().trim_end_matches('%');
            if let Ok(score) = s.parse::<f64>() {
                if (30.0..=100.0).contains(&score) {
                    let name = line[..m.start()]
                        .trim()
                        .trim_end_matches('-')
                        .trim()
                        .to_string();
                    if (3..=60).contains(&name.chars().count()) {
                        out.push(ScoreEntry { name, score });
                    }
                }
            }
        }
    }
    out
}

// ── Borda count merge ──────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct ArenaModel {
    pub name: String,
    pub elo: i64,
    pub consensus_score: i64,
    pub source_count: usize,
}

pub fn merge_multi_source_rankings(raw_texts: &BTreeMap<String, String>) -> Vec<ArenaModel> {
    let mut source_rankings: BTreeMap<String, Vec<ScoreEntry>> = BTreeMap::new();
    for (source_name, text) in raw_texts {
        if text.is_empty() {
            continue;
        }
        let mut models = parse_scores_from_text(text);
        // Dedup by name (keep highest score).
        let mut seen: HashMap<String, ScoreEntry> = HashMap::new();
        for m in models.drain(..) {
            let key = m.name.to_lowercase();
            seen.entry(key)
                .and_modify(|cur| {
                    if m.score > cur.score {
                        *cur = m.clone();
                    }
                })
                .or_insert(m);
        }
        let mut ranked: Vec<ScoreEntry> = seen.into_values().collect();
        ranked.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
        source_rankings.insert(source_name.clone(), ranked);
    }

    if source_rankings.is_empty() {
        return Vec::new();
    }

    #[derive(Debug, Clone)]
    struct Acc {
        name: String,
        total_points: i64,
        source_count: usize,
        best_score: f64,
    }
    let mut model_points: HashMap<String, Acc> = HashMap::new();
    for ranked in source_rankings.values() {
        for (rank, m) in ranked.iter().take(100).enumerate() {
            let key = m.name.to_lowercase();
            let points = (100 - rank as i64).max(0);
            let entry = model_points.entry(key).or_insert(Acc {
                name: m.name.clone(),
                total_points: 0,
                source_count: 0,
                best_score: 0.0,
            });
            entry.total_points += points;
            entry.source_count += 1;
            if m.score > entry.best_score {
                entry.best_score = m.score;
                entry.name = m.name.clone();
            }
        }
    }

    for acc in model_points.values_mut() {
        if acc.source_count >= 3 {
            acc.total_points = (acc.total_points as f64 * 1.5) as i64;
        } else if acc.source_count >= 2 {
            acc.total_points = (acc.total_points as f64 * 1.2) as i64;
        }
    }

    let mut merged: Vec<Acc> = model_points.into_values().collect();
    merged.sort_by(|a, b| b.total_points.cmp(&a.total_points));
    merged
        .into_iter()
        .map(|m| ArenaModel {
            name: m.name,
            elo: if m.best_score >= 1000.0 {
                m.best_score as i64
            } else {
                0
            },
            consensus_score: m.total_points,
            source_count: m.source_count,
        })
        .collect()
}

// ── Catalog generation ─────────────────────────────────────────

fn name_lower_contains_any(name_lower: &str, kws: &[&str]) -> bool {
    kws.iter().any(|kw| name_lower.contains(kw))
}

fn name_lower_contains_set(name_lower: &str, set: &BTreeSet<String>) -> bool {
    set.iter().any(|kw| name_lower.contains(kw.as_str()))
}

fn infer_provider(name: &str) -> String {
    let lower = name.to_lowercase();
    let mapping: &[(&str, &str)] = &[
        ("grok", "xAI"),
        ("glm", "Z.AI"),
        ("kimi", "Moonshot"),
        ("minimax", "MiniMax"),
        ("deepseek", "DeepSeek"),
        ("qwen", "Qwen"),
        ("gemini", "Google"),
    ];
    for (kw, prov) in mapping {
        if lower.contains(kw) {
            return (*prov).to_string();
        }
    }
    name.split('-').next().unwrap_or(name).to_string()
}

fn category_note(cat: &str) -> &'static str {
    match cat {
        "coding" => "SWE-Bench 領先",
        "reasoning" => "數學推理強",
        "chinese" => "中文 Arena 排名最高",
        "speed" => "出字速度最快",
        "cost" => "品質/價格比最高",
        _ => "",
    }
}

pub fn generate_benchmark_highlights(
    arena_models: &[ArenaModel],
    configured: &BTreeSet<String>,
) -> Map<String, Value> {
    let mut configured_with_elo: Vec<(usize, &ArenaModel)> = Vec::new();
    for (idx, m) in arena_models.iter().enumerate() {
        let lower = m.name.to_lowercase();
        let is_configured = name_lower_contains_set(&lower, configured);
        let is_big3 = name_lower_contains_any(&lower, BIG3_KEYWORDS);
        if is_configured && !is_big3 {
            configured_with_elo.push((idx, m));
        }
    }

    let mut highlights = Map::new();
    if let Some((idx, best)) = configured_with_elo.first().copied() {
        highlights.insert(
            "overall".to_string(),
            json!({
                "name": best.name,
                "provider": infer_provider(&best.name),
                "score": format!("{} Elo", best.elo),
                "note": format!("LiteLLM 最強（Arena 排名 #{}）", idx + 1),
                "configured": true,
            }),
        );
    }

    let cats: &[(&str, &[&str])] = &[
        ("coding", &["grok", "gemini"]),
        ("reasoning", &["kimi", "deepseek-r"]),
        ("chinese", &["glm", "kimi", "qwen"]),
        ("speed", &["flash", "lite", "turbo"]),
        ("cost", &["deepseek-v3", "qwen3.5-flash"]),
    ];
    for (cat, kws) in cats {
        let mut best: Option<&ArenaModel> = None;
        for (_, m) in &configured_with_elo {
            let lower = m.name.to_lowercase();
            if name_lower_contains_any(&lower, kws) {
                if best.map_or(true, |cur| m.elo > cur.elo) {
                    best = Some(m);
                }
            }
        }
        if let Some(b) = best {
            highlights.insert(
                (*cat).to_string(),
                json!({
                    "name": b.name,
                    "provider": infer_provider(&b.name),
                    "score": format!("{} Elo", b.elo),
                    "note": category_note(cat),
                    "configured": true,
                }),
            );
        }
    }

    highlights
}

pub fn generate_scenarios(
    arena_models: &[ArenaModel],
    configured: &BTreeSet<String>,
) -> Vec<Value> {
    let best_for = |kws: &[&str]| -> (String, i64) {
        for m in arena_models {
            let lower = m.name.to_lowercase();
            let is_big3 = name_lower_contains_any(&lower, BIG3_KEYWORDS);
            let is_configured = name_lower_contains_set(&lower, configured);
            if is_configured && !is_big3 && name_lower_contains_any(&lower, kws) {
                return (m.name.clone(), m.elo);
            }
        }
        (String::new(), 0)
    };

    let tasks: &[(&str, &[&str], &[&str], &str)] = &[
        ("寫程式", &["grok"], &["gemini"], "SWE-Bench"),
        ("中文內容", &["glm"], &["kimi"], "Arena Chinese"),
        ("數學推理", &["kimi"], &["deepseek-r"], "AIME"),
        ("研究分析", &["gemini"], &["grok"], "Intelligence"),
        ("快速草稿", &["flash", "qwen3.5-flash"], &["lite"], "速度+成本"),
        ("Agent 任務", &["kimi"], &["minimax"], "BrowseComp"),
        ("省錢至上", &["deepseek-v3"], &["qwen3.5-flash"], "$/M tokens"),
    ];

    let mut out = Vec::new();
    for (task, best_kw, alt_kw, prefix) in tasks {
        let (best_name, best_elo) = best_for(best_kw);
        if best_name.is_empty() {
            continue;
        }
        let (alt_name, _alt_elo) = best_for(alt_kw);
        let elo_str = if best_elo > 0 {
            format!("{} Elo", best_elo)
        } else {
            String::new()
        };
        let reason = format!("{} {}", prefix, elo_str).trim().to_string();
        out.push(json!({
            "task": task,
            "best": best_name,
            "alt": if alt_name.is_empty() { "—".to_string() } else { alt_name },
            "reason": reason,
        }));
    }
    out
}

/// Top N models with Big-3 (OpenAI/Claude/Gemini) families filtered out.
///
/// Different from `notable_unconfigured`: this list keeps configured
/// providers (grok/glm/kimi/...) so the user sees the *full* non-Big-3
/// competitive landscape, not just hidden gems. Score is the consensus
/// Borda-count points so ranking is comparable across LiveBench (0-100)
/// and Arena (Elo 1100-1600) sources.
pub fn generate_non_big3_ranking(arena_models: &[ArenaModel], top_n: usize) -> Vec<Value> {
    let mut out = Vec::new();
    for m in arena_models {
        let lower = m.name.to_lowercase();
        if name_lower_contains_any(&lower, BIG3_KEYWORDS) {
            continue;
        }
        let entry = serde_json::json!({
            "rank": out.len() + 1,
            "name": m.name,
            "provider": infer_provider(&m.name),
            "consensus_score": m.consensus_score,
            "source_count": m.source_count,
        });
        out.push(entry);
        if out.len() >= top_n {
            break;
        }
    }
    out
}

pub fn generate_notable_unconfigured(
    arena_models: &[ArenaModel],
    configured: &BTreeSet<String>,
) -> Vec<Value> {
    let provider_enrichment: &[(&str, &str, &str, &str)] = &[
        ("mistral", "Mistral AI", "Mistral API / OpenRouter", "$2.00/$6.00"),
        ("llama", "Meta（開源）", "Fireworks / Together.ai", "$0.80~1.50/M"),
        ("reka", "Reka AI", "Reka API + SDK", "~$2~3/M"),
        ("doubao", "ByteDance", "豆包 API（中國區）", "~¥0.008/千 tokens"),
        ("command", "Cohere", "Cohere API", "$2.50/$10.00"),
        ("nemo", "Mistral AI", "Fireworks / Together.ai", "$0.10/$0.20"),
        ("yi", "01.AI", "01.AI API / OpenRouter", "~$1.00/$3.00"),
        ("step", "StepFun 階躍", "Step API（中國區）", "~¥0.05/千 tokens"),
        ("phi", "Microsoft", "Azure / HuggingFace", "開源免費"),
        ("jamba", "AI21 Labs", "AI21 API", "~$0.50/$0.70"),
        ("intern", "上海 AI Lab", "OpenRouter / HuggingFace", "開源"),
    ];

    let mut out = Vec::new();
    for m in arena_models {
        let lower = m.name.to_lowercase();
        if name_lower_contains_any(&lower, BIG3_KEYWORDS) {
            continue;
        }
        if name_lower_contains_set(&lower, configured) {
            continue;
        }

        let mut provider = "Unknown".to_string();
        let mut access = "待查".to_string();
        let mut price = "—".to_string();
        for (kw, prov, acc, pr) in provider_enrichment {
            if lower.contains(kw) {
                provider = (*prov).to_string();
                access = (*acc).to_string();
                price = (*pr).to_string();
                break;
            }
        }
        if provider == "Unknown" {
            provider = m
                .name
                .split('-')
                .next()
                .and_then(|s| s.split(' ').next())
                .unwrap_or(&m.name)
                .to_string();
        }

        out.push(json!({
            "name": m.name,
            "provider": provider,
            "score": format!("{} Elo", m.elo),
            "strengths": format!("Arena {} Elo", m.elo),
            "access": access,
            "price": price,
        }));

        if out.len() >= 6 {
            break;
        }
    }
    out
}

pub fn generate_subjective(config: &LitellmConfig) -> Map<String, Value> {
    let has_model = |needle: &str| -> bool {
        let needle_lower = needle.to_lowercase();
        config
            .models
            .iter()
            .any(|m| m.name.to_lowercase().contains(&needle_lower))
    };

    let mut picks: Map<String, Value> = Map::new();

    let smart_candidates: &[(&str, &str, &str)] = &[
        ("grok-4.20", "xAI", "2M context 旗艦，config 標註最強"),
        ("gemini-3.1-pro", "Google", "旗艦推理"),
        ("qwen3-max", "Qwen", "最強推理"),
    ];
    for (name, provider, note) in smart_candidates {
        if has_model(name) {
            picks.insert(
                "smart".to_string(),
                json!({"name": name, "provider": provider, "note": note}),
            );
            break;
        }
    }

    let fast_candidates: &[(&str, &str, &str)] = &[
        ("qwen3.5-flash", "Qwen", "$0.10/$0.40 全場最低 input 價"),
        ("grok-4.1-fast", "xAI", "$0.20/$0.50 非推理極速"),
        ("gemini-3.1-flash-lite", "Google", "$0.25/$1.50 極速"),
    ];
    for (name, provider, note) in fast_candidates {
        if has_model(name) {
            picks.insert(
                "fast".to_string(),
                json!({"name": name, "provider": provider, "note": note}),
            );
            break;
        }
    }

    let value_candidates: &[(&str, &str, &str)] = &[
        ("deepseek-v3", "DeepSeek", "$0.28/$0.42 地板價"),
        ("glm-4.5-air", "Z.AI", "$0.20/$1.10 便宜好用"),
    ];
    for (name, provider, note) in value_candidates {
        if has_model(name) {
            picks.insert(
                "value".to_string(),
                json!({"name": name, "provider": provider, "note": note}),
            );
            break;
        }
    }

    let free_candidates: &[(&str, &str, &str)] =
        &[("gemini-2.5-flash", "Google", "仍免費，但 2025/12 速率限制砍半")];
    for (name, provider, note) in free_candidates {
        if has_model(name) {
            picks.insert(
                "free".to_string(),
                json!({"name": name, "provider": provider, "note": note}),
            );
            break;
        }
    }

    picks
}

// ── Redis storage ──────────────────────────────────────────────

async fn store_full_catalog(redis_url: &str, data: &Value) -> bool {
    let client = match redis::Client::open(redis_url.to_string()) {
        Ok(c) => c,
        Err(_) => return false,
    };
    let mut conn = match redis::aio::ConnectionManager::new(client).await {
        Ok(c) => c,
        Err(_) => return false,
    };
    let payload = data.to_string();
    if conn
        .set_ex::<_, _, ()>(REDIS_KEY, payload.as_str(), REDIS_TTL_SECONDS)
        .await
        .is_err()
    {
        return false;
    }
    let notable_only = json!({
        "models": data.get("notable_unconfigured").cloned().unwrap_or(Value::Array(Vec::new())),
        "synced_at": data.get("synced_at").cloned().unwrap_or(Value::Null),
    });
    let _ = conn
        .set_ex::<_, _, ()>(
            REDIS_KEY_NOTABLE,
            notable_only.to_string(),
            REDIS_TTL_SECONDS,
        )
        .await;
    tracing::info!(
        key = REDIS_KEY,
        bytes = payload.len(),
        ttl_s = REDIS_TTL_SECONDS,
        "stored"
    );
    true
}

// ── Entry point ────────────────────────────────────────────────

pub async fn run_once(redis_url: &str) -> Result<bool> {
    let lock_file = File::create(LOCK_FILE_PATH)?;
    if lock_file.try_lock_exclusive().is_err() {
        tracing::info!(path = LOCK_FILE_PATH, "another sync already running — skip");
        return Ok(false);
    }

    tracing::info!("=== Model Catalog Full Sync Start (Multi-Source) ===");

    let config = parse_litellm_config();
    tracing::info!(
        providers = ?config.configured_providers,
        model_count = config.models.len(),
        "config parsed"
    );

    let raw_texts = scrape_all_sources().await;
    let sources_ok: Vec<String> = raw_texts
        .iter()
        .filter(|(_, v)| !v.is_empty())
        .map(|(k, _)| k.clone())
        .collect();
    tracing::info!(
        ok = sources_ok.len(),
        total = LEADERBOARD_SOURCES.len(),
        names = ?sources_ok,
        "sources scraped"
    );
    if sources_ok.is_empty() {
        tracing::error!("no data from any source");
        let _ = lock_file.unlock();
        return Ok(false);
    }

    let arena_models = merge_multi_source_rankings(&raw_texts);
    tracing::info!(
        models = arena_models.len(),
        sources = sources_ok.len(),
        "consensus ranking"
    );
    for (i, m) in arena_models.iter().take(10).enumerate() {
        tracing::info!(
            rank = i + 1,
            name = %m.name,
            score = m.consensus_score,
            srcs = m.source_count,
            "top"
        );
    }

    let synced_at = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false);
    let benchmark = generate_benchmark_highlights(&arena_models, &config.configured_providers);
    let scenarios = generate_scenarios(&arena_models, &config.configured_providers);
    let subjective = generate_subjective(&config);
    let notable = generate_notable_unconfigured(&arena_models, &config.configured_providers);
    // 非 Big3 排行 — 少爺要求永久內建：撇除 Claude/OpenAI/Gemini 系列，
    // 但保留 grok/glm/kimi/qwen/... 等 configured providers。
    let non_big3_ranking = generate_non_big3_ranking(&arena_models, 15);

    let full_catalog = json!({
        "highlights_benchmark": benchmark,
        "scenarios": scenarios,
        "highlights_subjective": subjective,
        "notable_unconfigured": notable,
        "non_big3_ranking": non_big3_ranking,
        "synced_at": synced_at,
        "sources_used": sources_ok,
        "source_count": sources_ok.len(),
        "consensus_model_count": arena_models.len(),
    });

    let stored = store_full_catalog(redis_url, &full_catalog).await;
    if !stored {
        tracing::warn!(path = FALLBACK_JSON_PATH, "redis store failed; writing fallback");
    }
    let _ = std::fs::write(
        FALLBACK_JSON_PATH,
        serde_json::to_string_pretty(&full_catalog).unwrap_or_default(),
    );

    tracing::info!(
        sources = sources_ok.len(),
        "=== Model Catalog Full Sync Done ==="
    );
    let _ = lock_file.unlock();
    Ok(stored)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_scores_picks_elo_and_pct() {
        let text = "\
GPT-5 1485\n\
Claude Opus 4.7 - 1462\n\
Grok 4.20 1455\n\
SomeBench 92.3%\n\
NoiseLine\n\
Bad 999\n\
TinyPct 12%\n\
";
        let scores = parse_scores_from_text(text);
        let names: Vec<&str> = scores.iter().map(|s| s.name.as_str()).collect();
        assert!(names.contains(&"GPT-5"));
        assert!(names.contains(&"Claude Opus 4.7"));
        assert!(names.contains(&"Grok 4.20"));
        assert!(names.contains(&"SomeBench"));
        assert!(!names.contains(&"Bad"));
        assert!(!names.contains(&"TinyPct"));
    }

    #[test]
    fn parse_scores_handles_livebench_tabs() {
        // Real-world LiveBench rows: header + 3 data rows + 1 footnote row.
        let text = "Model\tOrganization\tGlobal Average\tReasoning Average\n\
GPT-5.4 Thinking xHigh Effort\tOpenAI\t80.28\t88.12\n\
Claude 4.7 Opus Thinking xHigh Effort\tAnthropic\t76.91\t87.69\n\
Kimi K2.5 Thinking\tMoonshot AI\t69.07\t75.96\n\
*5th rank in unseen questions across all categories\tGoogle\t79.93\t84.00\n";
        let scores = parse_scores_from_text(text);
        let by_name: std::collections::HashMap<_, _> =
            scores.iter().map(|s| (s.name.as_str(), s.score)).collect();
        // Header row has no 30-100 float in any column → skipped.
        assert!(!by_name.contains_key("Model"));
        // Three real rows → parsed.
        assert_eq!(by_name.get("GPT-5.4 Thinking xHigh Effort"), Some(&80.28));
        assert_eq!(by_name.get("Claude 4.7 Opus Thinking xHigh Effort"), Some(&76.91));
        assert_eq!(by_name.get("Kimi K2.5 Thinking"), Some(&69.07));
        // Footnote row starts with '*' → rejected.
        assert!(!by_name.keys().any(|k| k.starts_with('*')));
    }

    #[test]
    fn merge_borda_with_multi_source_bonus() {
        let mut raw: BTreeMap<String, String> = BTreeMap::new();
        // Same model in 3 sources → gets 1.5x bonus.
        raw.insert("arena".into(), "Grok 4.20 1500\nKimi K2 1450\n".into());
        raw.insert(
            "livebench".into(),
            "Grok 4.20 1495\nGLM 4.5 1430\n".into(),
        );
        raw.insert(
            "openrouter".into(),
            "Grok 4.20 1490\nDeepSeek V3 1410\n".into(),
        );
        let merged = merge_multi_source_rankings(&raw);
        assert!(!merged.is_empty());
        // Grok appears in 3 sources → gets boosted, should be #1.
        assert_eq!(merged[0].name, "Grok 4.20");
        assert_eq!(merged[0].source_count, 3);
        // Total raw points = 100*3 = 300; with 1.5x → 450.
        assert_eq!(merged[0].consensus_score, 450);
    }

    #[test]
    fn benchmark_highlights_excludes_big3() {
        let configured: BTreeSet<String> =
            ["grok", "kimi", "glm"].iter().map(|s| s.to_string()).collect();
        let arena = vec![
            ArenaModel {
                name: "GPT-5".into(),
                elo: 1500,
                consensus_score: 500,
                source_count: 3,
            },
            ArenaModel {
                name: "Grok 4.20".into(),
                elo: 1480,
                consensus_score: 450,
                source_count: 3,
            },
            ArenaModel {
                name: "Kimi K2".into(),
                elo: 1430,
                consensus_score: 380,
                source_count: 2,
            },
        ];
        let h = generate_benchmark_highlights(&arena, &configured);
        let overall = h.get("overall").expect("overall present");
        // GPT-5 is Big-3 → skipped; Grok wins.
        assert_eq!(overall["name"], "Grok 4.20");
        assert_eq!(overall["provider"], "xAI");
    }

    #[test]
    fn non_big3_ranking_keeps_configured_drops_big3() {
        let arena = vec![
            ArenaModel {
                name: "GPT-5 Pro".into(),
                elo: 0,
                consensus_score: 100,
                source_count: 1,
            },
            ArenaModel {
                name: "Claude 4.7 Opus Thinking".into(),
                elo: 0,
                consensus_score: 99,
                source_count: 1,
            },
            ArenaModel {
                name: "Gemini 3 Pro".into(),
                elo: 0,
                consensus_score: 92,
                source_count: 1,
            },
            ArenaModel {
                name: "Kimi K2.5 Thinking".into(),
                elo: 0,
                consensus_score: 80,
                source_count: 1,
            },
            ArenaModel {
                name: "Qwen 3.6 Plus".into(),
                elo: 0,
                consensus_score: 75,
                source_count: 1,
            },
            ArenaModel {
                name: "Mistral Large".into(),
                elo: 0,
                consensus_score: 60,
                source_count: 1,
            },
        ];
        let r = generate_non_big3_ranking(&arena, 10);
        let names: Vec<&str> =
            r.iter().map(|v| v["name"].as_str().unwrap_or("")).collect();
        // Big-3 trio dropped.
        assert!(!names.contains(&"GPT-5 Pro"));
        assert!(!names.contains(&"Claude 4.7 Opus Thinking"));
        assert!(!names.contains(&"Gemini 3 Pro"));
        // Configured + hidden gem all kept, ranking densely from 1.
        assert_eq!(names, vec!["Kimi K2.5 Thinking", "Qwen 3.6 Plus", "Mistral Large"]);
        assert_eq!(r[0]["rank"], 1);
        assert_eq!(r[1]["rank"], 2);
        assert_eq!(r[2]["rank"], 3);
        assert_eq!(r[0]["provider"], "Moonshot");
        assert_eq!(r[1]["provider"], "Qwen");
    }

    #[test]
    fn non_big3_ranking_respects_top_n() {
        let arena: Vec<ArenaModel> = (0..30)
            .map(|i| ArenaModel {
                name: format!("model-{}", i),
                elo: 0,
                consensus_score: 100 - i,
                source_count: 1,
            })
            .collect();
        let r = generate_non_big3_ranking(&arena, 5);
        assert_eq!(r.len(), 5);
    }

    #[test]
    fn notable_skips_configured_and_big3() {
        let configured: BTreeSet<String> =
            ["grok", "kimi"].iter().map(|s| s.to_string()).collect();
        let arena = vec![
            ArenaModel {
                name: "GPT-5".into(),
                elo: 1500,
                consensus_score: 500,
                source_count: 3,
            },
            ArenaModel {
                name: "Grok 4.20".into(),
                elo: 1480,
                consensus_score: 450,
                source_count: 3,
            },
            ArenaModel {
                name: "Mistral Large".into(),
                elo: 1380,
                consensus_score: 300,
                source_count: 2,
            },
            ArenaModel {
                name: "Llama 4 Behemoth".into(),
                elo: 1370,
                consensus_score: 290,
                source_count: 2,
            },
        ];
        let notable = generate_notable_unconfigured(&arena, &configured);
        assert_eq!(notable.len(), 2);
        assert_eq!(notable[0]["provider"], "Mistral AI");
        assert_eq!(notable[1]["provider"], "Meta（開源）");
    }
}
