mod aggregator;
mod cache;
mod output;
mod parser;
mod pricing;
mod scanner;
mod types;

use anyhow::Result;
use chrono::NaiveDate;
use clap::{CommandFactory, Parser, Subcommand, ValueEnum};
use clap_complete::{generate, Shell};
use std::time::Instant;

use rayon::prelude::*;

use crate::aggregator::*;
use crate::cache::CacheManager;
use crate::pricing::PricingTable;
use crate::scanner::*;
use crate::types::{AggregationResult, OutputConfig, UsageEntry};

#[derive(Parser)]
#[command(name = "ccusage", about = "Claude Code usage tracker (Rust)", version)]
struct Cli {
    #[command(subcommand)]
    command: Commands,

    /// Filter by project name (substring match)
    #[arg(long, global = true)]
    project: Option<String>,

    /// Filter by model name (substring match, e.g. "opus")
    #[arg(long, global = true)]
    model: Option<String>,

    /// Start date (YYYYMMDD or YYYY-MM-DD)
    #[arg(long, global = true)]
    since: Option<String>,

    /// End date (YYYYMMDD or YYYY-MM-DD)
    #[arg(long, global = true)]
    until: Option<String>,

    /// Output as JSON
    #[arg(long, global = true, group = "output_format")]
    json: bool,

    /// Output as CSV
    #[arg(long, global = true, group = "output_format")]
    csv: bool,

    /// Show per-model breakdown
    #[arg(long, global = true)]
    breakdown: bool,

    /// Use offline pricing (no network)
    #[arg(long, global = true)]
    offline: bool,

    /// Disable cache
    #[arg(long, global = true)]
    no_cache: bool,

    /// Hide cost columns (token-only view)
    #[arg(long, global = true)]
    no_cost: bool,

    /// Disable colored output (for piping)
    #[arg(long, global = true)]
    no_color: bool,

    /// Sort order
    #[arg(long, global = true, value_enum)]
    order: Option<SortOrder>,

    /// Limit number of results (for session/instances)
    #[arg(long, global = true)]
    limit: Option<usize>,

    /// Override timezone (e.g. "Asia/Taipei", default: system local)
    #[arg(long, global = true)]
    tz: Option<String>,

    /// Block offset hours (shifts 5h block boundaries, default: 0)
    #[arg(long, global = true, default_value = "0")]
    block_offset: i64,
}

#[derive(Clone, ValueEnum)]
enum SortOrder {
    Asc,
    Desc,
}

#[derive(Subcommand)]
enum Commands {
    /// Show daily usage
    Daily,
    /// Show monthly usage
    Monthly,
    /// Show weekly usage
    Weekly,
    /// Show per-session usage (use --id for single session detail)
    Session {
        /// Session ID prefix to look up (e.g. first 8 characters)
        #[arg(long)]
        id: Option<String>,
    },
    /// Show 5-hour billing blocks
    Blocks,
    /// Compact one-line output for tmux statusline
    Statusline,
    /// Show usage grouped by project (cwd)
    Instances,
    /// Show per-session sub-agent breakdown (use --id for single session)
    Agent {
        /// Session ID prefix to look up (e.g. first 8 characters)
        #[arg(long)]
        id: Option<String>,
    },
    /// Generate shell completions
    Completions {
        /// Shell type
        #[arg(value_enum)]
        shell: Shell,
    },
}

fn parse_date(s: &str) -> Result<NaiveDate> {
    if s.contains('-') {
        Ok(NaiveDate::parse_from_str(s, "%Y-%m-%d")?)
    } else {
        Ok(NaiveDate::parse_from_str(s, "%Y%m%d")?)
    }
}

/// Get today's date in user-specified or system local timezone
fn local_today(tz: &Option<String>) -> NaiveDate {
    if let Some(tz_str) = tz {
        if let Ok(tz) = tz_str.parse::<chrono_tz::Tz>() {
            return chrono::Utc::now().with_timezone(&tz).date_naive();
        }
    }
    chrono::Local::now().date_naive()
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    // Handle completions subcommand (no data processing needed)
    if let Commands::Completions { shell } = &cli.command {
        let mut cmd = Cli::command();
        generate(*shell, &mut cmd, "ccusage", &mut std::io::stdout());
        return Ok(());
    }

    let start_time = Instant::now();

    // Build output config
    let out_cfg = OutputConfig {
        no_cost: cli.no_cost,
        no_color: cli.no_color,
        csv: cli.csv,
        limit: cli.limit,
    };

    // Parse date filters
    let since = cli.since.as_ref().map(|s| parse_date(s)).transpose()?;
    let until = cli.until.as_ref().map(|s| parse_date(s)).transpose()?;

    if let (Some(s), Some(u)) = (since, until) {
        if s > u {
            anyhow::bail!("--since ({s}) is after --until ({u})");
        }
    }

    // Use local timezone for default since date
    let today = local_today(&cli.tz);
    let since = since.or(
        if matches!(cli.command, Commands::Daily | Commands::Statusline) {
            Some(today)
        } else {
            None
        }
    );

    // Load pricing (non-blocking if cache exists)
    let pricing = PricingTable::load(cli.offline);

    // Scan ALL files (cache is global, project filter applied after)
    let projects_dir = default_projects_dir();
    let all_files = scan_jsonl_files(&projects_dir)?;
    let file_count = all_files.len();

    let cache = CacheManager::new();

    // Load/parse entries with incremental cache (operates on full file set)
    let all_entries: Vec<UsageEntry> = if cli.no_cache {
        dedup_entries(parse_files_parallel(&all_files))
    } else {
        match cache.load_all() {
            Some((cached_mtimes, cached_raw, _cached_entries)) => {
                let changed = cache.files_needing_reparse(&all_files, &cached_mtimes);
                let removed = cache.removed_files(&all_files, &cached_mtimes);

                if changed.is_empty() && removed.is_empty() {
                    if !matches!(cli.command, Commands::Statusline) {
                        let entry_count = cached_raw.len();
                        eprintln!("  cache: hit ({} entries)", entry_count);
                    }
                    // Convert cached raw to usage entries
                    dedup_entries(cached_raw
                        .iter()
                        .filter_map(|e| e.to_usage_entry())
                        .collect())
                } else {
                    // Incremental: keep entries from unchanged files, reparse changed ones
                    let changed_paths: std::collections::HashSet<String> = changed
                        .iter()
                        .map(|f| f.path.to_string_lossy().to_string())
                        .collect();
                    let removed_paths: std::collections::HashSet<String> =
                        removed.iter().cloned().collect();

                    // Retain cached entries from unchanged files
                    let mut kept_cached: Vec<crate::cache::CachedEntry> = cached_raw
                        .into_iter()
                        .filter(|e| {
                            !changed_paths.contains(&e.source_file)
                                && !removed_paths.contains(&e.source_file)
                        })
                        .collect();

                    // Parse changed files and build cached entries
                    let new_cached: Vec<crate::cache::CachedEntry> = changed
                        .par_iter()
                        .flat_map_iter(|f| {
                            let path_str = f.path.to_string_lossy().to_string();
                            crate::parser::parse_jsonl_file(&f.path)
                                .unwrap_or_default()
                                .into_iter()
                                .map(move |e| {
                                    crate::cache::CachedEntry::from_usage_entry(&e, &path_str)
                                })
                        })
                        .collect();

                    kept_cached.extend(new_cached);

                    // Convert to usage entries before saving
                    let entries: Vec<UsageEntry> = kept_cached
                        .iter()
                        .filter_map(|e| e.to_usage_entry())
                        .collect();

                    // Save incremental cache
                    let _ = cache.save_all_with_sources(&all_files, kept_cached);

                    if !matches!(cli.command, Commands::Statusline) {
                        eprintln!(
                            "  cache: {} changed, {} removed → incremental reparse",
                            changed_paths.len(),
                            removed_paths.len()
                        );
                    }

                    dedup_entries(entries)
                }
            }
            None => {
                // No cache — full parse with source tracking
                let mut all_cached: Vec<crate::cache::CachedEntry> = Vec::new();
                for f in &all_files {
                    let path_str = f.path.to_string_lossy().to_string();
                    if let Ok(file_entries) = crate::parser::parse_jsonl_file(&f.path) {
                        for e in &file_entries {
                            all_cached.push(crate::cache::CachedEntry::from_usage_entry(
                                e, &path_str,
                            ));
                        }
                    }
                }

                let entries: Vec<UsageEntry> = all_cached
                    .iter()
                    .filter_map(|e| e.to_usage_entry())
                    .collect();
                let _ = cache.save_all_with_sources(&all_files, all_cached);
                dedup_entries(entries)
            }
        }
    };

    // Filter out synthetic/internal placeholder models
    let all_entries: Vec<UsageEntry> = all_entries
        .into_iter()
        .filter(|e| !e.model.starts_with('<'))
        .collect();

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

    // Apply model filter
    let entries = if let Some(ref model) = cli.model {
        filter_by_model(entries, model)
    } else {
        entries
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

    // Determine default sort direction per subcommand
    let desc = match &cli.order {
        Some(SortOrder::Desc) => true,
        Some(SortOrder::Asc) => false,
        None => matches!(cli.command, Commands::Session { .. } | Commands::Blocks | Commands::Instances | Commands::Agent { .. }),
    };

    // Aggregate and output
    let is_statusline = matches!(cli.command, Commands::Statusline);
    let entry_count = filtered.len();
    let print_stats = |elapsed: f64| {
        if !is_statusline {
            eprintln!(
                "  {} files, {} entries, {:.2}s",
                file_count, entry_count, elapsed
            );
        }
    };

    match cli.command {
        Commands::Daily => {
            let mut summaries = aggregate_daily(&filtered, &pricing);
            if desc {
                summaries.reverse();
            }
            if cli.json {
                output::print_json(&AggregationResult::Daily(summaries));
            } else {
                output::print_daily_table(&summaries, cli.breakdown, &out_cfg);
                print_stats(elapsed.as_secs_f64());
            }
        }
        Commands::Monthly => {
            let mut summaries = aggregate_monthly(&filtered, &pricing);
            if desc {
                summaries.reverse();
            }
            if cli.json {
                output::print_json(&AggregationResult::Monthly(summaries));
            } else {
                output::print_monthly_table(&summaries, cli.breakdown, &out_cfg);
                print_stats(elapsed.as_secs_f64());
            }
        }
        Commands::Weekly => {
            let mut summaries = aggregate_weekly(&filtered, &pricing);
            if desc {
                summaries.reverse();
            }
            if cli.json {
                output::print_json(&AggregationResult::Weekly(summaries));
            } else {
                output::print_weekly_table(&summaries, cli.breakdown, &out_cfg);
                print_stats(elapsed.as_secs_f64());
            }
        }
        Commands::Session { id } => {
            let mut summaries = aggregate_sessions(&filtered, &pricing);
            if !desc {
                summaries.reverse(); // default is desc by cost, reverse for asc
            }

            if let Some(ref prefix) = id {
                if prefix.is_empty() {
                    anyhow::bail!("--id requires a non-empty value");
                }
                // Session ID lookup by prefix
                let prefix_lower = prefix.to_lowercase();
                let matches: Vec<_> = summaries
                    .into_iter()
                    .filter(|s| s.session_id.to_lowercase().starts_with(&prefix_lower))
                    .collect();

                match matches.len() {
                    0 => {
                        eprintln!("No session found matching prefix \"{}\"", prefix);
                        std::process::exit(1);
                    }
                    1 => {
                        if cli.json {
                            output::print_json(&AggregationResult::Session(matches));
                        } else {
                            output::print_session_detail(&matches[0], &out_cfg);
                            print_stats(elapsed.as_secs_f64());
                        }
                    }
                    _ => {
                        eprintln!(
                            "  {} sessions match prefix \"{}\"",
                            matches.len(),
                            prefix
                        );
                        if cli.json {
                            output::print_json(&AggregationResult::Session(matches));
                        } else {
                            output::print_session_table(&matches, &out_cfg);
                            print_stats(elapsed.as_secs_f64());
                        }
                    }
                }
            } else {
                if cli.json {
                    output::print_json(&AggregationResult::Session(summaries));
                } else {
                    output::print_session_table(&summaries, &out_cfg);
                    print_stats(elapsed.as_secs_f64());
                }
            }
        }
        Commands::Blocks => {
            let mut summaries = aggregate_blocks(&filtered, &pricing, cli.block_offset);
            if desc {
                summaries.reverse();
            }
            if cli.json {
                output::print_json(&AggregationResult::Blocks(summaries));
            } else {
                output::print_block_table(&summaries, &out_cfg);
                print_stats(elapsed.as_secs_f64());
            }
        }
        Commands::Statusline => {
            let summaries = aggregate_blocks(&filtered, &pricing, cli.block_offset);
            output::print_statusline(&summaries, &cli.tz, cli.block_offset);
        }
        Commands::Instances => {
            let mut summaries = aggregate_instances(&filtered, &pricing);
            if !desc {
                summaries.reverse(); // default is desc by cost
            }
            if cli.json {
                output::print_json(&AggregationResult::Instances(summaries));
            } else {
                output::print_instance_table(&summaries, &out_cfg);
                print_stats(elapsed.as_secs_f64());
            }
        }
        Commands::Agent { id } => {
            let summaries = aggregate_agents(&filtered, &pricing);

            if let Some(ref prefix) = id {
                if prefix.is_empty() {
                    anyhow::bail!("--id requires a non-empty value");
                }
                let prefix_lower = prefix.to_lowercase();
                let matches: Vec<_> = summaries
                    .into_iter()
                    .filter(|s| s.session_id.to_lowercase().starts_with(&prefix_lower))
                    .collect();

                match matches.len() {
                    0 => {
                        eprintln!("No session with agents found matching prefix \"{}\"", prefix);
                        std::process::exit(1);
                    }
                    1 => {
                        if cli.json {
                            output::print_json(&AggregationResult::Agents(matches));
                        } else {
                            output::print_agent_detail(&matches[0], &out_cfg);
                            print_stats(elapsed.as_secs_f64());
                        }
                    }
                    _ => {
                        eprintln!(
                            "  {} sessions match prefix \"{}\"",
                            matches.len(),
                            prefix
                        );
                        if cli.json {
                            output::print_json(&AggregationResult::Agents(matches));
                        } else {
                            output::print_agent_table(&matches, &out_cfg);
                            print_stats(elapsed.as_secs_f64());
                        }
                    }
                }
            } else if cli.json {
                output::print_json(&AggregationResult::Agents(summaries));
            } else {
                output::print_agent_table(&summaries, &out_cfg);
                print_stats(elapsed.as_secs_f64());
            }
        }
        Commands::Completions { .. } => unreachable!(),
    }

    Ok(())
}
