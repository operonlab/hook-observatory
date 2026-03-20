use anyhow::Result;
use chrono::{DateTime, Utc};
use simd_json::prelude::*;
use std::io::{BufRead, BufReader};
use std::path::Path;

use crate::types::UsageEntry;

/// Parse a single JSONL file, extracting only assistant entries with usage data.
/// Uses byte-level pre-filtering to skip ~75% of lines without JSON parsing.
pub fn parse_jsonl_file(path: &Path) -> Result<Vec<UsageEntry>> {
    let file = std::fs::File::open(path)?;
    let reader = BufReader::with_capacity(64 * 1024, file);
    let mut entries = Vec::new();

    for line in reader.lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => continue,
        };

        // Fast byte-level pre-filter: skip lines that can't be assistant+usage
        if !line.contains("\"assistant\"") || !line.contains("\"usage\"") {
            continue;
        }

        // Skip file-history-snapshot entries (may contain "assistant" in content)
        if line.contains("\"file-history-snapshot\"") {
            continue;
        }

        // Parse JSON
        let mut bytes = line.into_bytes();
        let value: simd_json::OwnedValue = match simd_json::to_owned_value(&mut bytes) {
            Ok(v) => v,
            Err(_) => continue,
        };

        // Verify type == "assistant"
        let type_val: Option<&str> = value.get_str("type");
        if type_val != Some("assistant") {
            continue;
        }

        // Extract fields
        let entry = match extract_usage_entry(&value) {
            Some(e) => e,
            None => continue,
        };

        entries.push(entry);
    }

    Ok(entries)
}

fn extract_usage_entry(value: &simd_json::OwnedValue) -> Option<UsageEntry> {
    let timestamp_str: &str = value.get_str("timestamp")?;
    let timestamp: DateTime<Utc> = timestamp_str.parse().ok()?;

    let session_id = value.get_str("sessionId")?.to_string();
    let cwd = value.get_str("cwd").map(String::from);

    let message = value.get("message")?;
    let model = message.get_str("model")?.to_string();
    let message_id = message.get_str("id").map(String::from);
    let usage = message.get("usage")?;

    let input_tokens = usage.get_u64("input_tokens").unwrap_or(0);
    let output_tokens = usage.get_u64("output_tokens").unwrap_or(0);

    // Parse cache creation: prefer ephemeral breakdown, fallback to flat field as 1h
    // (Claude Code always uses 1h ephemeral cache)
    let (cache_creation_5m, cache_creation_1h) = if let Some(cc) = usage.get("cache_creation") {
        (
            cc.get_u64("ephemeral_5m_input_tokens").unwrap_or(0),
            cc.get_u64("ephemeral_1h_input_tokens").unwrap_or(0),
        )
    } else {
        // Legacy: no breakdown → treat as 1h (CC always uses 1h cache)
        (0, usage.get_u64("cache_creation_input_tokens").unwrap_or(0))
    };

    let cache_read_tokens = usage.get_u64("cache_read_input_tokens").unwrap_or(0);
    let thinking_tokens = usage.get_u64("thinking_tokens").unwrap_or(0);
    let speed = usage.get_str("speed").map(String::from);

    // Filter empty streaming placeholders (no message id + zero tokens)
    if message_id.is_none() && input_tokens == 0 && output_tokens == 0 {
        return None;
    }

    Some(UsageEntry {
        timestamp,
        session_id,
        message_id,
        model,
        cwd,
        input_tokens,
        output_tokens,
        cache_creation_5m_tokens: cache_creation_5m,
        cache_creation_1h_tokens: cache_creation_1h,
        cache_read_tokens,
        thinking_tokens,
        speed,
    })
}
