mod aggregator;
mod cache;
mod output;
mod parser;
mod pricing;
mod scanner;
mod types;

use anyhow::Result;
use chrono::{NaiveDate, Utc};
use clap::{Parser, Subcommand};
use std::time::Instant;

use crate::aggregator::*;
use crate::cache::CacheManager;
use crate::pricing::PricingTable;
use crate::scanner::*;
use crate::types::{AggregationResult, UsageEntry};

#[derive(Parser)]
#[command(name = "ccusage-rs", about = "Claude Code usage tracker (Rust)", version)]
struct Cli {
    #[command(subcommand)]
    command: Commands,

    /// Filter by project name (substring match)
    #[arg(long, global = true)]
    project: Option<String>,

    /// Start date (YYYYMMDD)
    #[arg(long, global = true)]
    since: Option<String>,

    /// End date (YYYYMMDD)
    #[arg(long, global = true)]
    until: Option<String>,

    /// Output as JSON
    #[arg(long, global = true)]
    json: bool,

    /// Show per-model breakdown
    #[arg(long, global = true)]
    breakdown: bool,

    /// Use offline pricing (no network)
    #[arg(long, global = true)]
    offline: bool,

    /// Disable cache
    #[arg(long, global = true)]
    no_cache: bool,
}

#[derive(Subcommand)]
enum Commands {
    /// Show daily usage
    Daily,
    /// Show monthly usage
    Monthly,
    /// Show weekly usage
    Weekly,
    /// Show per-session usage
    Session,
    /// Show 5-hour billing blocks
    Blocks,
}

fn parse_date(s: &str) -> Result<NaiveDate> {
    if s.contains('-') {
        Ok(NaiveDate::parse_from_str(s, "%Y-%m-%d")?)
    } else {
        Ok(NaiveDate::parse_from_str(s, "%Y%m%d")?)
    }
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let start_time = Instant::now();

    // Parse date filters
    let since = cli.since.as_ref().map(|s| parse_date(s)).transpose()?;
    let until = cli.until.as_ref().map(|s| parse_date(s)).transpose()?;

    let since = since.or_else(|| {
        if matches!(cli.command, Commands::Daily) {
            Some(Utc::now().date_naive())
        } else {
            None
        }
    });

    // Load pricing (non-blocking if cache exists)
    let pricing = PricingTable::load(cli.offline);

    // Scan ALL files (cache is global, project filter applied after)
    let projects_dir = default_projects_dir();
    let all_files = scan_jsonl_files(&projects_dir)?;
    let file_count = all_files.len();

    let cache = CacheManager::new();
    let today = Utc::now().date_naive();

    // Load/parse entries with incremental cache (operates on full file set)
    let all_entries: Vec<UsageEntry> = if cli.no_cache {
        parse_files_parallel(&all_files)
    } else {
        match cache.load_all() {
            Some((cached_mtimes, cached_entries)) => {
                let changed = cache.files_needing_reparse(&all_files, &cached_mtimes);
                let removed = cache.removed_files(&all_files, &cached_mtimes);

                if changed.is_empty() && removed.is_empty() {
                    eprintln!("  cache: hit ({} entries)", cached_entries.len());
                    cached_entries
                } else {
                    // Any change → full reparse (simple, correct, still fast at 0.5s)
                    let entries = parse_files_parallel(&all_files);
                    let _ = cache.save_all(&all_files, &entries);
                    eprintln!(
                        "  cache: {} changed, {} new → reparse",
                        changed.len(),
                        removed.len()
                    );
                    entries
                }
            }
            None => {
                let entries = parse_files_parallel(&all_files);
                let _ = cache.save_all(&all_files, &entries);
                entries
            }
        }
    };

    // Apply project filter after cache
    let entries = if let Some(ref project) = cli.project {
        let project_lower = project.to_lowercase();
        all_entries
            .into_iter()
            .filter(|e| {
                e.cwd
                    .as_ref()
                    .is_some_and(|c| c.to_lowercase().contains(&project_lower))
            })
            .collect()
    } else {
        all_entries
    };

    // Apply date filter
    let filtered = filter_by_date(entries, since, until);
    let elapsed = start_time.elapsed();

    // Cache daily summaries for frozen dates
    if !cli.no_cache && matches!(cli.command, Commands::Daily) {
        let dailies = aggregate_daily(&filtered, &pricing);
        for summary in &dailies {
            if summary.date < today {
                let _ = cache.save_daily(summary);
            }
        }
    }

    // Aggregate and output
    let entry_count = filtered.len();
    let print_stats = |elapsed: f64| {
        eprintln!(
            "  {} files, {} entries, {:.2}s",
            file_count, entry_count, elapsed
        );
    };

    match cli.command {
        Commands::Daily => {
            let summaries = aggregate_daily(&filtered, &pricing);
            if cli.json {
                output::print_json(&AggregationResult::Daily(summaries));
            } else {
                output::print_daily_table(&summaries, cli.breakdown);
                print_stats(elapsed.as_secs_f64());
            }
        }
        Commands::Monthly => {
            let summaries = aggregate_monthly(&filtered, &pricing);
            if cli.json {
                output::print_json(&AggregationResult::Monthly(summaries));
            } else {
                output::print_monthly_table(&summaries, cli.breakdown);
                print_stats(elapsed.as_secs_f64());
            }
        }
        Commands::Weekly => {
            let summaries = aggregate_weekly(&filtered, &pricing);
            if cli.json {
                output::print_json(&AggregationResult::Weekly(summaries));
            } else {
                output::print_weekly_table(&summaries, cli.breakdown);
                print_stats(elapsed.as_secs_f64());
            }
        }
        Commands::Session => {
            let summaries = aggregate_sessions(&filtered, &pricing);
            if cli.json {
                output::print_json(&AggregationResult::Session(summaries));
            } else {
                output::print_session_table(&summaries);
                print_stats(elapsed.as_secs_f64());
            }
        }
        Commands::Blocks => {
            let summaries = aggregate_blocks(&filtered, &pricing);
            if cli.json {
                output::print_json(&AggregationResult::Blocks(summaries));
            } else {
                output::print_block_table(&summaries);
                print_stats(elapsed.as_secs_f64());
            }
        }
    }

    Ok(())
}
