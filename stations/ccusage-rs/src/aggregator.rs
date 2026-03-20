use chrono::{Datelike, Duration, NaiveDate};
use rayon::prelude::*;
use std::collections::{HashMap, HashSet};

use crate::pricing::PricingTable;
use crate::types::*;

/// Aggregate usage entries into daily summaries
pub fn aggregate_daily(
    entries: &[UsageEntry],
    pricing: &PricingTable,
) -> Vec<DailySummary> {
    let mut daily: HashMap<NaiveDate, DailySummary> = HashMap::new();

    for entry in entries {
        let date = entry.timestamp.date_naive();
        let tokens = entry_to_tokens(entry);
        let cost = pricing.calculate_cost(&entry.model, &tokens, entry.speed.as_deref());

        let summary = daily.entry(date).or_insert_with(|| DailySummary {
            date,
            total_tokens: TokenCounts::default(),
            total_cost: 0.0,
            by_model: HashMap::new(),
        });

        summary.total_tokens.merge(&tokens);
        summary.total_cost += cost.total();

        let model_usage = summary
            .by_model
            .entry(entry.model.clone())
            .or_default();
        model_usage.tokens.merge(&tokens);
        model_usage.cost.merge(&cost);
    }

    let mut result: Vec<DailySummary> = daily.into_values().collect();
    result.sort_by_key(|s| s.date);
    result
}

/// Aggregate usage entries into monthly summaries
pub fn aggregate_monthly(
    entries: &[UsageEntry],
    pricing: &PricingTable,
) -> Vec<MonthlySummary> {
    let mut monthly: HashMap<(i32, u32), MonthlySummary> = HashMap::new();

    for entry in entries {
        let date = entry.timestamp.date_naive();
        let key = (date.year(), date.month());
        let tokens = entry_to_tokens(entry);
        let cost = pricing.calculate_cost(&entry.model, &tokens, entry.speed.as_deref());

        let summary = monthly.entry(key).or_insert_with(|| MonthlySummary {
            year: key.0,
            month: key.1,
            total_tokens: TokenCounts::default(),
            total_cost: 0.0,
            by_model: HashMap::new(),
        });

        summary.total_tokens.merge(&tokens);
        summary.total_cost += cost.total();

        let model_usage = summary
            .by_model
            .entry(entry.model.clone())
            .or_default();
        model_usage.tokens.merge(&tokens);
        model_usage.cost.merge(&cost);
    }

    let mut result: Vec<MonthlySummary> = monthly.into_values().collect();
    result.sort_by_key(|s| (s.year, s.month));
    result
}

/// Aggregate usage entries into weekly summaries (Monday-start weeks)
pub fn aggregate_weekly(
    entries: &[UsageEntry],
    pricing: &PricingTable,
) -> Vec<WeeklySummary> {
    let mut weekly: HashMap<NaiveDate, WeeklySummary> = HashMap::new();

    for entry in entries {
        let date = entry.timestamp.date_naive();
        let week_start = date
            - Duration::days(date.weekday().num_days_from_monday() as i64);
        let week_end = week_start + Duration::days(6);
        let tokens = entry_to_tokens(entry);
        let cost = pricing.calculate_cost(&entry.model, &tokens, entry.speed.as_deref());

        let summary = weekly.entry(week_start).or_insert_with(|| WeeklySummary {
            week_start,
            week_end,
            total_tokens: TokenCounts::default(),
            total_cost: 0.0,
            by_model: HashMap::new(),
        });

        summary.total_tokens.merge(&tokens);
        summary.total_cost += cost.total();

        let model_usage = summary
            .by_model
            .entry(entry.model.clone())
            .or_default();
        model_usage.tokens.merge(&tokens);
        model_usage.cost.merge(&cost);
    }

    let mut result: Vec<WeeklySummary> = weekly.into_values().collect();
    result.sort_by_key(|s| s.week_start);
    result
}

/// Aggregate usage entries into session summaries
pub fn aggregate_sessions(
    entries: &[UsageEntry],
    pricing: &PricingTable,
) -> Vec<SessionUsage> {
    let mut sessions: HashMap<String, SessionUsage> = HashMap::new();

    for entry in entries {
        let date = entry.timestamp.date_naive();
        let tokens = entry_to_tokens(entry);
        let cost = pricing.calculate_cost(&entry.model, &tokens, entry.speed.as_deref());

        let session = sessions
            .entry(entry.session_id.clone())
            .or_insert_with(|| SessionUsage {
                session_id: entry.session_id.clone(),
                date,
                project: entry.cwd.as_ref().and_then(|c| {
                    c.rsplit('/').next().map(String::from)
                }),
                total_tokens: TokenCounts::default(),
                total_cost: 0.0,
                by_model: HashMap::new(),
                first_activity: None,
                last_activity: None,
                fast_entry_count: 0,
            });

        // Track first/last activity timestamps
        match session.first_activity {
            Some(t) if entry.timestamp < t => session.first_activity = Some(entry.timestamp),
            None => session.first_activity = Some(entry.timestamp),
            _ => {}
        }
        match session.last_activity {
            Some(t) if entry.timestamp > t => session.last_activity = Some(entry.timestamp),
            None => session.last_activity = Some(entry.timestamp),
            _ => {}
        }

        if entry.speed.as_deref() == Some("fast") {
            session.fast_entry_count += 1;
        }

        session.total_tokens.merge(&tokens);
        session.total_cost += cost.total();

        let model_usage = session
            .by_model
            .entry(entry.model.clone())
            .or_default();
        model_usage.tokens.merge(&tokens);
        model_usage.cost.merge(&cost);
    }

    let mut result: Vec<SessionUsage> = sessions.into_values().collect();
    result.sort_by(|a, b| {
        b.total_cost
            .partial_cmp(&a.total_cost)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    result
}

/// Aggregate into 5-hour billing blocks with optional hour offset
pub fn aggregate_blocks(
    entries: &[UsageEntry],
    pricing: &PricingTable,
    offset_hours: i64,
) -> Vec<BlockSummary> {
    use chrono::Timelike;

    let mut blocks: HashMap<i64, BlockSummary> = HashMap::new();

    for entry in entries {
        let ts = entry.timestamp;
        // Apply offset: shift timestamp so blocks align to offset hour
        let shifted = ts - Duration::hours(offset_hours);
        // Calculate 5-hour block start based on shifted time
        let hour_block = (shifted.hour() / 5) * 5;
        let block_start = shifted
            .date_naive()
            .and_hms_opt(hour_block, 0, 0)
            .unwrap()
            .and_utc()
            + Duration::hours(offset_hours);
        let block_end = block_start + Duration::hours(5);
        let block_key = block_start.timestamp();

        let tokens = entry_to_tokens(entry);
        let cost = pricing.calculate_cost(&entry.model, &tokens, entry.speed.as_deref());

        let block = blocks.entry(block_key).or_insert_with(|| BlockSummary {
            block_start,
            block_end,
            total_tokens: TokenCounts::default(),
            total_cost: 0.0,
            by_model: HashMap::new(),
        });

        block.total_tokens.merge(&tokens);
        block.total_cost += cost.total();

        let model_usage = block
            .by_model
            .entry(entry.model.clone())
            .or_default();
        model_usage.tokens.merge(&tokens);
        model_usage.cost.merge(&cost);
    }

    let mut result: Vec<BlockSummary> = blocks.into_values().collect();
    result.sort_by_key(|b| b.block_start);
    result
}

/// Parse all files in parallel and return combined entries
pub fn parse_files_parallel(files: &[FileInfo]) -> Vec<UsageEntry> {
    files
        .par_iter()
        .flat_map(|file| {
            crate::parser::parse_jsonl_file(&file.path).unwrap_or_default()
        })
        .collect()
}

/// Filter entries by date range
pub fn filter_by_date(
    entries: Vec<UsageEntry>,
    since: Option<NaiveDate>,
    until: Option<NaiveDate>,
) -> Vec<UsageEntry> {
    entries
        .into_iter()
        .filter(|e| {
            let date = e.timestamp.date_naive();
            if let Some(s) = since {
                if date < s {
                    return false;
                }
            }
            if let Some(u) = until {
                if date > u {
                    return false;
                }
            }
            true
        })
        .collect()
}

/// Filter entries by model name (substring match)
pub fn filter_by_model(entries: Vec<UsageEntry>, model: &str) -> Vec<UsageEntry> {
    let model_lower = model.to_lowercase();
    entries
        .into_iter()
        .filter(|e| e.model.to_lowercase().contains(&model_lower))
        .collect()
}

/// Aggregate usage entries by project (cwd) into instance summaries
pub fn aggregate_instances(
    entries: &[UsageEntry],
    pricing: &PricingTable,
) -> Vec<InstanceUsage> {
    let mut instances: HashMap<String, InstanceUsage> = HashMap::new();
    let mut session_sets: HashMap<String, std::collections::HashSet<String>> = HashMap::new();

    for entry in entries {
        let project = entry
            .cwd
            .clone()
            .unwrap_or_else(|| "unknown".to_string());
        let tokens = entry_to_tokens(entry);
        let cost = pricing.calculate_cost(&entry.model, &tokens, entry.speed.as_deref());

        session_sets
            .entry(project.clone())
            .or_default()
            .insert(entry.session_id.clone());

        let instance = instances.entry(project.clone()).or_insert_with(|| InstanceUsage {
            project,
            session_count: 0,
            total_tokens: TokenCounts::default(),
            total_cost: 0.0,
            by_model: HashMap::new(),
        });

        instance.total_tokens.merge(&tokens);
        instance.total_cost += cost.total();

        let model_usage = instance
            .by_model
            .entry(entry.model.clone())
            .or_default();
        model_usage.tokens.merge(&tokens);
        model_usage.cost.merge(&cost);
    }

    // Fill in session counts
    let mut result: Vec<InstanceUsage> = instances
        .into_iter()
        .map(|(key, mut inst)| {
            inst.session_count = session_sets.get(&key).map(|s| s.len()).unwrap_or(0);
            inst
        })
        .collect();

    result.sort_by(|a, b| {
        b.total_cost
            .partial_cmp(&a.total_cost)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    result
}

/// Deduplicate entries: by (session_id, message_id) when message_id exists,
/// fallback to (session_id, timestamp_ms, model) for legacy entries
pub fn dedup_entries(entries: Vec<UsageEntry>) -> Vec<UsageEntry> {
    let mut seen_msg: HashSet<(String, String)> = HashSet::new();
    let mut seen_ts: HashSet<(String, i64, String)> = HashSet::new();
    entries
        .into_iter()
        .filter(|e| {
            if let Some(ref mid) = e.message_id {
                let key = (e.session_id.clone(), mid.clone());
                seen_msg.insert(key)
            } else {
                let key = (
                    e.session_id.clone(),
                    e.timestamp.timestamp_millis(),
                    e.model.clone(),
                );
                seen_ts.insert(key)
            }
        })
        .collect()
}

fn entry_to_tokens(entry: &UsageEntry) -> TokenCounts {
    TokenCounts {
        input_tokens: entry.input_tokens,
        output_tokens: entry.output_tokens,
        cache_creation_5m_tokens: entry.cache_creation_5m_tokens,
        cache_creation_1h_tokens: entry.cache_creation_1h_tokens,
        cache_read_tokens: entry.cache_read_tokens,
        thinking_tokens: entry.thinking_tokens,
    }
}
