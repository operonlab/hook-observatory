use chrono::{Datelike, Duration, NaiveDate};
use rayon::prelude::*;
use std::collections::HashMap;

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
                slug: None,
                total_tokens: TokenCounts::default(),
                total_cost: 0.0,
                by_model: HashMap::new(),
                first_activity: None,
                last_activity: None,
                fast_entry_count: 0,
            });

        // Pick up first non-None slug from entries
        if session.slug.is_none() {
            if let Some(ref s) = entry.slug {
                session.slug = Some(s.clone());
            }
        }

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

/// Aggregate usage entries into per-session agent summaries.
/// Only includes sessions that have at least one sub-agent entry.
pub fn aggregate_agents(
    entries: &[UsageEntry],
    pricing: &PricingTable,
) -> Vec<SessionAgentSummary> {
    // Group entries by session_id
    let mut by_session: HashMap<String, Vec<&UsageEntry>> = HashMap::new();
    for entry in entries {
        by_session
            .entry(entry.session_id.clone())
            .or_default()
            .push(entry);
    }

    let mut summaries: Vec<SessionAgentSummary> = Vec::new();

    for (session_id, session_entries) in &by_session {
        // Check if this session has any agent entries
        let has_agents = session_entries.iter().any(|e| e.agent_id.is_some());
        if !has_agents {
            continue;
        }

        // Group by agent_id (None = main thread)
        let mut by_agent: HashMap<Option<String>, Vec<&UsageEntry>> = HashMap::new();
        for entry in session_entries {
            by_agent
                .entry(entry.agent_id.clone())
                .or_default()
                .push(entry);
        }

        // Session-level slug and project
        let slug = session_entries
            .iter()
            .find_map(|e| e.slug.clone());
        let project = session_entries
            .iter()
            .find_map(|e| {
                e.cwd
                    .as_ref()
                    .and_then(|c| c.rsplit('/').next().map(String::from))
            });

        // Calculate total session cost
        let total_cost: f64 = session_entries
            .iter()
            .map(|e| {
                let tokens = entry_to_tokens(e);
                pricing.calculate_cost(&e.model, &tokens, e.speed.as_deref()).total()
            })
            .sum();

        // Build per-agent usage
        let mut agents: Vec<AgentUsage> = Vec::new();
        let mut main_cost = 0.0;

        for (agent_id, agent_entries) in &by_agent {
            let mut tokens = TokenCounts::default();
            let mut cost = 0.0;
            let mut by_model: HashMap<String, ModelUsage> = HashMap::new();

            for entry in agent_entries {
                let t = entry_to_tokens(entry);
                let c = pricing.calculate_cost(&entry.model, &t, entry.speed.as_deref());
                tokens.merge(&t);
                cost += c.total();

                let model_usage = by_model.entry(entry.model.clone()).or_default();
                model_usage.tokens.merge(&t);
                model_usage.cost.merge(&c);
            }

            // Determine primary model for this agent
            let primary_model = by_model
                .iter()
                .max_by(|a, b| {
                    a.1.cost
                        .total()
                        .partial_cmp(&b.1.cost.total())
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .map(|(m, _)| m.clone());

            if agent_id.is_none() {
                main_cost = cost;
            }

            agents.push(AgentUsage {
                agent_id: agent_id.clone(),
                model: primary_model,
                tokens,
                cost,
                cost_pct: 0.0, // filled below
                entry_count: agent_entries.len(),
                by_model,
            });
        }

        // Fill cost_pct
        if total_cost > 0.0 {
            for a in &mut agents {
                a.cost_pct = (a.cost / total_cost) * 100.0;
            }
        }

        let main_pct = if total_cost > 0.0 {
            (main_cost / total_cost) * 100.0
        } else {
            0.0
        };

        // Sort agents: main thread first, then by cost desc
        agents.sort_by(|a, b| {
            match (&a.agent_id, &b.agent_id) {
                (None, _) => std::cmp::Ordering::Less,
                (_, None) => std::cmp::Ordering::Greater,
                _ => b.cost.partial_cmp(&a.cost).unwrap_or(std::cmp::Ordering::Equal),
            }
        });

        summaries.push(SessionAgentSummary {
            session_id: session_id.clone(),
            slug,
            project,
            total_cost,
            main_cost,
            main_pct,
            agents,
        });
    }

    // Sort by total_cost desc
    summaries.sort_by(|a, b| {
        b.total_cost
            .partial_cmp(&a.total_cost)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    summaries
}

/// Deduplicate entries using last-wins strategy: by (session_id, message_id) when
/// message_id exists, fallback to (session_id, timestamp_ms, model) for legacy entries.
/// Last-wins ensures streaming snapshots retain the final output_tokens value (#888).
pub fn dedup_entries(entries: Vec<UsageEntry>) -> Vec<UsageEntry> {
    let mut by_msg: HashMap<(String, String), usize> = HashMap::new();
    let mut by_ts: HashMap<(String, i64, String), usize> = HashMap::new();
    let mut result: Vec<Option<UsageEntry>> = Vec::with_capacity(entries.len());

    for entry in entries {
        if let Some(ref mid) = entry.message_id {
            let key = (entry.session_id.clone(), mid.clone());
            if let Some(&prev_idx) = by_msg.get(&key) {
                result[prev_idx] = None;
            }
            by_msg.insert(key, result.len());
        } else {
            let key = (
                entry.session_id.clone(),
                entry.timestamp.timestamp_millis(),
                entry.model.clone(),
            );
            if let Some(&prev_idx) = by_ts.get(&key) {
                result[prev_idx] = None;
            }
            by_ts.insert(key, result.len());
        }
        result.push(Some(entry));
    }

    result.into_iter().flatten().collect()
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
