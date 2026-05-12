use chrono::{DateTime, Utc};
use comfy_table::{presets::UTF8_FULL_CONDENSED, Attribute, Cell, CellAlignment, Color, Table};

use crate::types::*;

/// Format currency
fn fmt_cost(cost: f64) -> String {
    if cost < 0.01 {
        format!("${:.4}", cost)
    } else {
        format!("${:.2}", cost)
    }
}

/// Format token count with comma separators
fn fmt_tokens(n: u64) -> String {
    let s = n.to_string();
    let mut result = String::new();
    for (i, c) in s.chars().rev().enumerate() {
        if i > 0 && i % 3 == 0 {
            result.push(',');
        }
        result.push(c);
    }
    result.chars().rev().collect()
}

/// Format token count in compact form (e.g., 1.2M, 45K)
fn fmt_tokens_compact(n: u64) -> String {
    if n >= 1_000_000 {
        format!("{:.1}M", n as f64 / 1_000_000.0)
    } else if n >= 1_000 {
        format!("{:.1}K", n as f64 / 1_000.0)
    } else {
        n.to_string()
    }
}

/// Format session duration from first/last activity timestamps
fn fmt_duration(first: Option<DateTime<Utc>>, last: Option<DateTime<Utc>>) -> String {
    match (first, last) {
        (Some(f), Some(l)) => {
            let total_mins = (l - f).num_minutes();
            if total_mins < 1 {
                "<1m".to_string()
            } else if total_mins < 60 {
                format!("{}m", total_mins)
            } else {
                let hours = total_mins / 60;
                let mins = total_mins % 60;
                if mins == 0 {
                    format!("{}h", hours)
                } else {
                    format!("{}h{}m", hours, mins)
                }
            }
        }
        _ => "-".to_string(),
    }
}

/// Truncate a string to max_len characters, appending "…" if truncated
fn truncate_str(s: &str, max_len: usize) -> String {
    if s.chars().count() <= max_len {
        s.to_string()
    } else {
        let truncated: String = s.chars().take(max_len - 1).collect();
        format!("{}…", truncated)
    }
}

/// Escape a CSV field (quote if contains comma, quote, or newline)
fn csv_escape(s: &str) -> String {
    if s.contains(',') || s.contains('"') || s.contains('\n') {
        format!("\"{}\"", s.replace('"', "\"\""))
    } else {
        s.to_string()
    }
}

fn new_table(cfg: &OutputConfig) -> Table {
    let mut table = Table::new();
    table.load_preset(UTF8_FULL_CONDENSED);
    if cfg.no_color {
        table.force_no_tty();
    }
    table
}

/// Check if any summary has non-zero thinking tokens
fn has_thinking_tokens_daily(summaries: &[DailySummary]) -> bool {
    summaries
        .iter()
        .any(|s| s.total_tokens.thinking_tokens > 0)
}

fn has_thinking_tokens_monthly(summaries: &[MonthlySummary]) -> bool {
    summaries
        .iter()
        .any(|s| s.total_tokens.thinking_tokens > 0)
}

fn has_thinking_tokens_weekly(summaries: &[WeeklySummary]) -> bool {
    summaries
        .iter()
        .any(|s| s.total_tokens.thinking_tokens > 0)
}

// ─── Daily ───────────────────────────────────────────

pub fn print_daily_table(summaries: &[DailySummary], breakdown: bool, cfg: &OutputConfig) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    if cfg.csv {
        print_daily_csv(summaries, breakdown, cfg);
        return;
    }

    if breakdown {
        print_daily_breakdown(summaries, cfg);
        return;
    }

    let show_thinking = has_thinking_tokens_daily(summaries);
    let mut table = new_table(cfg);
    let mut header = vec![
        Cell::new("Date").add_attribute(Attribute::Bold),
        Cell::new("Input").add_attribute(Attribute::Bold),
        Cell::new("Output").add_attribute(Attribute::Bold),
        Cell::new("Cache Write").add_attribute(Attribute::Bold),
        Cell::new("Cache Read").add_attribute(Attribute::Bold),
    ];
    if show_thinking {
        header.push(Cell::new("Thinking").add_attribute(Attribute::Bold));
    }
    header.push(Cell::new("Total Tokens").add_attribute(Attribute::Bold));
    if !cfg.no_cost {
        header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
    }
    table.set_header(header);

    let mut grand_tokens = TokenCounts::default();
    let mut grand_cost = 0.0;

    for s in summaries {
        let mut row = vec![
            Cell::new(s.date.format("%Y-%m-%d").to_string()),
            Cell::new(fmt_tokens(s.total_tokens.input_tokens)).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.output_tokens)).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.cache_creation_tokens()))
                .set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.cache_read_tokens))
                .set_alignment(CellAlignment::Right),
        ];
        if show_thinking {
            row.push(
                Cell::new(fmt_tokens(s.total_tokens.thinking_tokens))
                    .set_alignment(CellAlignment::Right),
            );
        }
        row.push(
            Cell::new(fmt_tokens(s.total_tokens.total_tokens()))
                .set_alignment(CellAlignment::Right),
        );
        if !cfg.no_cost {
            row.push(
                Cell::new(fmt_cost(s.total_cost))
                    .set_alignment(CellAlignment::Right)
                    .fg(Color::Green),
            );
        }
        table.add_row(row);
        grand_tokens.merge(&s.total_tokens);
        grand_cost += s.total_cost;
    }

    // Total row
    let mut total_row = vec![
        Cell::new("TOTAL")
            .add_attribute(Attribute::Bold)
            .fg(Color::Yellow),
        Cell::new(fmt_tokens(grand_tokens.input_tokens))
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold),
        Cell::new(fmt_tokens(grand_tokens.output_tokens))
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold),
        Cell::new(fmt_tokens(grand_tokens.cache_creation_tokens()))
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold),
        Cell::new(fmt_tokens(grand_tokens.cache_read_tokens))
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold),
    ];
    if show_thinking {
        total_row.push(
            Cell::new(fmt_tokens(grand_tokens.thinking_tokens))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
        );
    }
    total_row.push(
        Cell::new(fmt_tokens(grand_tokens.total_tokens()))
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold),
    );
    if !cfg.no_cost {
        total_row.push(
            Cell::new(fmt_cost(grand_cost))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold)
                .fg(Color::Green),
        );
    }
    table.add_row(total_row);

    println!("{table}");
}

fn print_daily_breakdown(summaries: &[DailySummary], cfg: &OutputConfig) {
    let mut table = new_table(cfg);
    let mut header = vec![
        Cell::new("Date").add_attribute(Attribute::Bold),
        Cell::new("Model").add_attribute(Attribute::Bold),
        Cell::new("Input").add_attribute(Attribute::Bold),
        Cell::new("Output").add_attribute(Attribute::Bold),
        Cell::new("Cache Write").add_attribute(Attribute::Bold),
        Cell::new("Cache Read").add_attribute(Attribute::Bold),
    ];
    if !cfg.no_cost {
        header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
    }
    table.set_header(header);

    for s in summaries {
        let mut models: Vec<_> = s.by_model.iter().collect();
        models.sort_by(|a, b| {
            b.1.cost
                .total()
                .partial_cmp(&a.1.cost.total())
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        for (i, (model, usage)) in models.iter().enumerate() {
            let date_str = if i == 0 {
                s.date.format("%Y-%m-%d").to_string()
            } else {
                String::new()
            };

            let mut row = vec![
                Cell::new(date_str),
                Cell::new(model).fg(Color::Cyan),
                Cell::new(fmt_tokens(usage.tokens.input_tokens))
                    .set_alignment(CellAlignment::Right),
                Cell::new(fmt_tokens(usage.tokens.output_tokens))
                    .set_alignment(CellAlignment::Right),
                Cell::new(fmt_tokens(usage.tokens.cache_creation_tokens()))
                    .set_alignment(CellAlignment::Right),
                Cell::new(fmt_tokens(usage.tokens.cache_read_tokens))
                    .set_alignment(CellAlignment::Right),
            ];
            if !cfg.no_cost {
                row.push(
                    Cell::new(fmt_cost(usage.cost.total()))
                        .set_alignment(CellAlignment::Right)
                        .fg(Color::Green),
                );
            }
            table.add_row(row);
        }
    }

    println!("{table}");
}

fn print_daily_csv(summaries: &[DailySummary], breakdown: bool, cfg: &OutputConfig) {
    if breakdown {
        if cfg.no_cost {
            println!("Date,Model,Input,Output,Cache Write,Cache Read");
        } else {
            println!("Date,Model,Input,Output,Cache Write,Cache Read,Cost");
        }
        for s in summaries {
            for (model, usage) in &s.by_model {
                if cfg.no_cost {
                    println!(
                        "{},{},{},{},{},{}",
                        s.date.format("%Y-%m-%d"),
                        csv_escape(model),
                        usage.tokens.input_tokens,
                        usage.tokens.output_tokens,
                        usage.tokens.cache_creation_tokens(),
                        usage.tokens.cache_read_tokens,
                    );
                } else {
                    println!(
                        "{},{},{},{},{},{},{:.6}",
                        s.date.format("%Y-%m-%d"),
                        csv_escape(model),
                        usage.tokens.input_tokens,
                        usage.tokens.output_tokens,
                        usage.tokens.cache_creation_tokens(),
                        usage.tokens.cache_read_tokens,
                        usage.cost.total(),
                    );
                }
            }
        }
    } else {
        let show_thinking = has_thinking_tokens_daily(summaries);
        if cfg.no_cost {
            if show_thinking {
                println!("Date,Input,Output,Cache Write,Cache Read,Thinking,Total");
            } else {
                println!("Date,Input,Output,Cache Write,Cache Read,Total");
            }
        } else if show_thinking {
            println!("Date,Input,Output,Cache Write,Cache Read,Thinking,Total,Cost");
        } else {
            println!("Date,Input,Output,Cache Write,Cache Read,Total,Cost");
        }
        for s in summaries {
            print!(
                "{},{},{},{},{}",
                s.date.format("%Y-%m-%d"),
                s.total_tokens.input_tokens,
                s.total_tokens.output_tokens,
                s.total_tokens.cache_creation_tokens(),
                s.total_tokens.cache_read_tokens,
            );
            if show_thinking {
                print!(",{}", s.total_tokens.thinking_tokens);
            }
            print!(",{}", s.total_tokens.total_tokens());
            if !cfg.no_cost {
                print!(",{:.6}", s.total_cost);
            }
            println!();
        }
    }
}

// ─── Monthly ─────────────────────────────────────────

pub fn print_monthly_table(summaries: &[MonthlySummary], breakdown: bool, cfg: &OutputConfig) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    if cfg.csv {
        print_monthly_csv(summaries, breakdown, cfg);
        return;
    }

    let mut table = new_table(cfg);

    if breakdown {
        let mut header = vec![
            Cell::new("Month").add_attribute(Attribute::Bold),
            Cell::new("Model").add_attribute(Attribute::Bold),
            Cell::new("Input").add_attribute(Attribute::Bold),
            Cell::new("Output").add_attribute(Attribute::Bold),
            Cell::new("Cache Write").add_attribute(Attribute::Bold),
            Cell::new("Cache Read").add_attribute(Attribute::Bold),
        ];
        if !cfg.no_cost {
            header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
        }
        table.set_header(header);

        for s in summaries {
            let mut models: Vec<_> = s.by_model.iter().collect();
            models.sort_by(|a, b| {
                b.1.cost
                    .total()
                    .partial_cmp(&a.1.cost.total())
                    .unwrap_or(std::cmp::Ordering::Equal)
            });

            for (i, (model, usage)) in models.iter().enumerate() {
                let month_str = if i == 0 {
                    format!("{}-{:02}", s.year, s.month)
                } else {
                    String::new()
                };

                let mut row = vec![
                    Cell::new(month_str),
                    Cell::new(model).fg(Color::Cyan),
                    Cell::new(fmt_tokens(usage.tokens.input_tokens))
                        .set_alignment(CellAlignment::Right),
                    Cell::new(fmt_tokens(usage.tokens.output_tokens))
                        .set_alignment(CellAlignment::Right),
                    Cell::new(fmt_tokens(usage.tokens.cache_creation_tokens()))
                        .set_alignment(CellAlignment::Right),
                    Cell::new(fmt_tokens(usage.tokens.cache_read_tokens))
                        .set_alignment(CellAlignment::Right),
                ];
                if !cfg.no_cost {
                    row.push(
                        Cell::new(fmt_cost(usage.cost.total()))
                            .set_alignment(CellAlignment::Right)
                            .fg(Color::Green),
                    );
                }
                table.add_row(row);
            }
        }
    } else {
        let show_thinking = has_thinking_tokens_monthly(summaries);
        let mut header = vec![
            Cell::new("Month").add_attribute(Attribute::Bold),
            Cell::new("Input").add_attribute(Attribute::Bold),
            Cell::new("Output").add_attribute(Attribute::Bold),
            Cell::new("Cache Write").add_attribute(Attribute::Bold),
            Cell::new("Cache Read").add_attribute(Attribute::Bold),
        ];
        if show_thinking {
            header.push(Cell::new("Thinking").add_attribute(Attribute::Bold));
        }
        header.push(Cell::new("Total Tokens").add_attribute(Attribute::Bold));
        if !cfg.no_cost {
            header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
        }
        table.set_header(header);

        let mut grand_tokens = TokenCounts::default();
        let mut grand_cost = 0.0;

        for s in summaries {
            let mut row = vec![
                Cell::new(format!("{}-{:02}", s.year, s.month)),
                Cell::new(fmt_tokens(s.total_tokens.input_tokens))
                    .set_alignment(CellAlignment::Right),
                Cell::new(fmt_tokens(s.total_tokens.output_tokens))
                    .set_alignment(CellAlignment::Right),
                Cell::new(fmt_tokens(s.total_tokens.cache_creation_tokens()))
                    .set_alignment(CellAlignment::Right),
                Cell::new(fmt_tokens(s.total_tokens.cache_read_tokens))
                    .set_alignment(CellAlignment::Right),
            ];
            if show_thinking {
                row.push(
                    Cell::new(fmt_tokens(s.total_tokens.thinking_tokens))
                        .set_alignment(CellAlignment::Right),
                );
            }
            row.push(
                Cell::new(fmt_tokens(s.total_tokens.total_tokens()))
                    .set_alignment(CellAlignment::Right),
            );
            if !cfg.no_cost {
                row.push(
                    Cell::new(fmt_cost(s.total_cost))
                        .set_alignment(CellAlignment::Right)
                        .fg(Color::Green),
                );
            }
            table.add_row(row);
            grand_tokens.merge(&s.total_tokens);
            grand_cost += s.total_cost;
        }

        let mut total_row = vec![
            Cell::new("TOTAL")
                .add_attribute(Attribute::Bold)
                .fg(Color::Yellow),
            Cell::new(fmt_tokens(grand_tokens.input_tokens))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
            Cell::new(fmt_tokens(grand_tokens.output_tokens))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
            Cell::new(fmt_tokens(grand_tokens.cache_creation_tokens()))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
            Cell::new(fmt_tokens(grand_tokens.cache_read_tokens))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
        ];
        if show_thinking {
            total_row.push(
                Cell::new(fmt_tokens(grand_tokens.thinking_tokens))
                    .set_alignment(CellAlignment::Right)
                    .add_attribute(Attribute::Bold),
            );
        }
        total_row.push(
            Cell::new(fmt_tokens(grand_tokens.total_tokens()))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
        );
        if !cfg.no_cost {
            total_row.push(
                Cell::new(fmt_cost(grand_cost))
                    .set_alignment(CellAlignment::Right)
                    .add_attribute(Attribute::Bold)
                    .fg(Color::Green),
            );
        }
        table.add_row(total_row);
    }

    println!("{table}");
}

fn print_monthly_csv(summaries: &[MonthlySummary], breakdown: bool, cfg: &OutputConfig) {
    if breakdown {
        if cfg.no_cost {
            println!("Month,Model,Input,Output,Cache Write,Cache Read");
        } else {
            println!("Month,Model,Input,Output,Cache Write,Cache Read,Cost");
        }
        for s in summaries {
            let month_str = format!("{}-{:02}", s.year, s.month);
            for (model, usage) in &s.by_model {
                print!(
                    "{},{},{},{},{},{}",
                    month_str,
                    csv_escape(model),
                    usage.tokens.input_tokens,
                    usage.tokens.output_tokens,
                    usage.tokens.cache_creation_tokens(),
                    usage.tokens.cache_read_tokens,
                );
                if !cfg.no_cost {
                    print!(",{:.6}", usage.cost.total());
                }
                println!();
            }
        }
    } else {
        let show_thinking = has_thinking_tokens_monthly(summaries);
        if cfg.no_cost {
            if show_thinking {
                println!("Month,Input,Output,Cache Write,Cache Read,Thinking,Total");
            } else {
                println!("Month,Input,Output,Cache Write,Cache Read,Total");
            }
        } else if show_thinking {
            println!("Month,Input,Output,Cache Write,Cache Read,Thinking,Total,Cost");
        } else {
            println!("Month,Input,Output,Cache Write,Cache Read,Total,Cost");
        }
        for s in summaries {
            print!(
                "{}-{:02},{},{},{},{}",
                s.year,
                s.month,
                s.total_tokens.input_tokens,
                s.total_tokens.output_tokens,
                s.total_tokens.cache_creation_tokens(),
                s.total_tokens.cache_read_tokens,
            );
            if show_thinking {
                print!(",{}", s.total_tokens.thinking_tokens);
            }
            print!(",{}", s.total_tokens.total_tokens());
            if !cfg.no_cost {
                print!(",{:.6}", s.total_cost);
            }
            println!();
        }
    }
}

// ─── Weekly ──────────────────────────────────────────

pub fn print_weekly_table(summaries: &[WeeklySummary], breakdown: bool, cfg: &OutputConfig) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    if cfg.csv {
        print_weekly_csv(summaries, breakdown, cfg);
        return;
    }

    let mut table = new_table(cfg);

    if breakdown {
        // P3-8: Weekly breakdown now includes cache columns
        let mut header = vec![
            Cell::new("Week").add_attribute(Attribute::Bold),
            Cell::new("Model").add_attribute(Attribute::Bold),
            Cell::new("Input").add_attribute(Attribute::Bold),
            Cell::new("Output").add_attribute(Attribute::Bold),
            Cell::new("Cache Write").add_attribute(Attribute::Bold),
            Cell::new("Cache Read").add_attribute(Attribute::Bold),
        ];
        if !cfg.no_cost {
            header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
        }
        table.set_header(header);

        for s in summaries {
            let mut models: Vec<_> = s.by_model.iter().collect();
            models.sort_by(|a, b| {
                b.1.cost
                    .total()
                    .partial_cmp(&a.1.cost.total())
                    .unwrap_or(std::cmp::Ordering::Equal)
            });

            for (i, (model, usage)) in models.iter().enumerate() {
                let week_str = if i == 0 {
                    format!(
                        "{} ~ {}",
                        s.week_start.format("%m-%d"),
                        s.week_end.format("%m-%d")
                    )
                } else {
                    String::new()
                };

                let mut row = vec![
                    Cell::new(week_str),
                    Cell::new(model).fg(Color::Cyan),
                    Cell::new(fmt_tokens(usage.tokens.input_tokens))
                        .set_alignment(CellAlignment::Right),
                    Cell::new(fmt_tokens(usage.tokens.output_tokens))
                        .set_alignment(CellAlignment::Right),
                    Cell::new(fmt_tokens(usage.tokens.cache_creation_tokens()))
                        .set_alignment(CellAlignment::Right),
                    Cell::new(fmt_tokens(usage.tokens.cache_read_tokens))
                        .set_alignment(CellAlignment::Right),
                ];
                if !cfg.no_cost {
                    row.push(
                        Cell::new(fmt_cost(usage.cost.total()))
                            .set_alignment(CellAlignment::Right)
                            .fg(Color::Green),
                    );
                }
                table.add_row(row);
            }
        }
    } else {
        let show_thinking = has_thinking_tokens_weekly(summaries);
        let mut header = vec![
            Cell::new("Week").add_attribute(Attribute::Bold),
            Cell::new("Input").add_attribute(Attribute::Bold),
            Cell::new("Output").add_attribute(Attribute::Bold),
            Cell::new("Cache Write").add_attribute(Attribute::Bold),
            Cell::new("Cache Read").add_attribute(Attribute::Bold),
        ];
        if show_thinking {
            header.push(Cell::new("Thinking").add_attribute(Attribute::Bold));
        }
        header.push(Cell::new("Total Tokens").add_attribute(Attribute::Bold));
        if !cfg.no_cost {
            header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
        }
        table.set_header(header);

        let mut grand_tokens = TokenCounts::default();
        let mut grand_cost = 0.0;

        for s in summaries {
            let mut row = vec![
                Cell::new(format!(
                    "{} ~ {}",
                    s.week_start.format("%m-%d"),
                    s.week_end.format("%m-%d")
                )),
                Cell::new(fmt_tokens(s.total_tokens.input_tokens))
                    .set_alignment(CellAlignment::Right),
                Cell::new(fmt_tokens(s.total_tokens.output_tokens))
                    .set_alignment(CellAlignment::Right),
                Cell::new(fmt_tokens(s.total_tokens.cache_creation_tokens()))
                    .set_alignment(CellAlignment::Right),
                Cell::new(fmt_tokens(s.total_tokens.cache_read_tokens))
                    .set_alignment(CellAlignment::Right),
            ];
            if show_thinking {
                row.push(
                    Cell::new(fmt_tokens(s.total_tokens.thinking_tokens))
                        .set_alignment(CellAlignment::Right),
                );
            }
            row.push(
                Cell::new(fmt_tokens(s.total_tokens.total_tokens()))
                    .set_alignment(CellAlignment::Right),
            );
            if !cfg.no_cost {
                row.push(
                    Cell::new(fmt_cost(s.total_cost))
                        .set_alignment(CellAlignment::Right)
                        .fg(Color::Green),
                );
            }
            table.add_row(row);
            grand_tokens.merge(&s.total_tokens);
            grand_cost += s.total_cost;
        }

        let mut total_row = vec![
            Cell::new("TOTAL")
                .add_attribute(Attribute::Bold)
                .fg(Color::Yellow),
            Cell::new(fmt_tokens(grand_tokens.input_tokens))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
            Cell::new(fmt_tokens(grand_tokens.output_tokens))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
            Cell::new(fmt_tokens(grand_tokens.cache_creation_tokens()))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
            Cell::new(fmt_tokens(grand_tokens.cache_read_tokens))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
        ];
        if show_thinking {
            total_row.push(
                Cell::new(fmt_tokens(grand_tokens.thinking_tokens))
                    .set_alignment(CellAlignment::Right)
                    .add_attribute(Attribute::Bold),
            );
        }
        total_row.push(
            Cell::new(fmt_tokens(grand_tokens.total_tokens()))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
        );
        if !cfg.no_cost {
            total_row.push(
                Cell::new(fmt_cost(grand_cost))
                    .set_alignment(CellAlignment::Right)
                    .add_attribute(Attribute::Bold)
                    .fg(Color::Green),
            );
        }
        table.add_row(total_row);
    }

    println!("{table}");
}

fn print_weekly_csv(summaries: &[WeeklySummary], breakdown: bool, cfg: &OutputConfig) {
    if breakdown {
        if cfg.no_cost {
            println!("Week Start,Week End,Model,Input,Output,Cache Write,Cache Read");
        } else {
            println!("Week Start,Week End,Model,Input,Output,Cache Write,Cache Read,Cost");
        }
        for s in summaries {
            for (model, usage) in &s.by_model {
                print!(
                    "{},{},{},{},{},{},{}",
                    s.week_start.format("%Y-%m-%d"),
                    s.week_end.format("%Y-%m-%d"),
                    csv_escape(model),
                    usage.tokens.input_tokens,
                    usage.tokens.output_tokens,
                    usage.tokens.cache_creation_tokens(),
                    usage.tokens.cache_read_tokens,
                );
                if !cfg.no_cost {
                    print!(",{:.6}", usage.cost.total());
                }
                println!();
            }
        }
    } else {
        let show_thinking = has_thinking_tokens_weekly(summaries);
        if cfg.no_cost {
            if show_thinking {
                println!("Week Start,Week End,Input,Output,Cache Write,Cache Read,Thinking,Total");
            } else {
                println!("Week Start,Week End,Input,Output,Cache Write,Cache Read,Total");
            }
        } else if show_thinking {
            println!("Week Start,Week End,Input,Output,Cache Write,Cache Read,Thinking,Total,Cost");
        } else {
            println!("Week Start,Week End,Input,Output,Cache Write,Cache Read,Total,Cost");
        }
        for s in summaries {
            print!(
                "{},{},{},{},{},{}",
                s.week_start.format("%Y-%m-%d"),
                s.week_end.format("%Y-%m-%d"),
                s.total_tokens.input_tokens,
                s.total_tokens.output_tokens,
                s.total_tokens.cache_creation_tokens(),
                s.total_tokens.cache_read_tokens,
            );
            if show_thinking {
                print!(",{}", s.total_tokens.thinking_tokens);
            }
            print!(",{}", s.total_tokens.total_tokens());
            if !cfg.no_cost {
                print!(",{:.6}", s.total_cost);
            }
            println!();
        }
    }
}

// ─── Session ─────────────────────────────────────────

pub fn print_session_table(summaries: &[SessionUsage], cfg: &OutputConfig) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    let limit = cfg.limit.unwrap_or(30);

    // Check if any session has a slug
    let has_slugs = summaries.iter().any(|s| s.slug.is_some());

    if cfg.csv {
        let show_thinking = summaries.iter().any(|s| s.total_tokens.thinking_tokens > 0);
        if cfg.no_cost {
            if has_slugs {
                if show_thinking {
                    println!("Session,Slug,Date,Duration,Project,Thinking,Total Tokens");
                } else {
                    println!("Session,Slug,Date,Duration,Project,Total Tokens");
                }
            } else if show_thinking {
                println!("Session,Date,Duration,Project,Thinking,Total Tokens");
            } else {
                println!("Session,Date,Duration,Project,Total Tokens");
            }
        } else if has_slugs {
            if show_thinking {
                println!("Session,Slug,Date,Duration,Project,Thinking,Total Tokens,Cost");
            } else {
                println!("Session,Slug,Date,Duration,Project,Total Tokens,Cost");
            }
        } else if show_thinking {
            println!("Session,Date,Duration,Project,Thinking,Total Tokens,Cost");
        } else {
            println!("Session,Date,Duration,Project,Total Tokens,Cost");
        }
        for s in summaries.iter().take(limit) {
            let short_id = &s.session_id[..8.min(s.session_id.len())];
            let dur = fmt_duration(s.first_activity, s.last_activity);
            print!("{}", short_id);
            if has_slugs {
                print!(",{}", csv_escape(s.slug.as_deref().unwrap_or("-")));
            }
            print!(
                ",{},{},{}",
                s.date.format("%Y-%m-%d"),
                csv_escape(&dur),
                csv_escape(s.project.as_deref().unwrap_or("-")),
            );
            if show_thinking {
                print!(",{}", s.total_tokens.thinking_tokens);
            }
            print!(",{}", s.total_tokens.total_tokens());
            if !cfg.no_cost {
                print!(",{:.6}", s.total_cost);
            }
            println!();
        }
        return;
    }

    let mut table = new_table(cfg);
    let mut header = vec![
        Cell::new("Session").add_attribute(Attribute::Bold),
    ];
    if has_slugs {
        header.push(Cell::new("Slug").add_attribute(Attribute::Bold));
    }
    header.extend([
        Cell::new("Date").add_attribute(Attribute::Bold),
        Cell::new("Duration").add_attribute(Attribute::Bold),
        Cell::new("Project").add_attribute(Attribute::Bold),
        Cell::new("Total Tokens").add_attribute(Attribute::Bold),
    ]);
    if !cfg.no_cost {
        header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
    }
    table.set_header(header);

    for s in summaries.iter().take(limit) {
        let short_id = &s.session_id[..8.min(s.session_id.len())];
        let mut row = vec![
            Cell::new(short_id).fg(Color::Cyan),
        ];
        if has_slugs {
            let slug_display = s
                .slug
                .as_deref()
                .map(|sl| truncate_str(sl, 25))
                .unwrap_or_else(|| "-".to_string());
            row.push(Cell::new(slug_display));
        }
        row.extend([
            Cell::new(s.date.format("%Y-%m-%d").to_string()),
            Cell::new(fmt_duration(s.first_activity, s.last_activity))
                .set_alignment(CellAlignment::Right),
            Cell::new(s.project.as_deref().unwrap_or("-")),
            Cell::new(fmt_tokens(s.total_tokens.total_tokens()))
                .set_alignment(CellAlignment::Right),
        ]);
        if !cfg.no_cost {
            row.push(
                Cell::new(fmt_cost(s.total_cost))
                    .set_alignment(CellAlignment::Right)
                    .fg(Color::Green),
            );
        }
        table.add_row(row);
    }

    // Grand total row (sum of ALL sessions, not just displayed)
    let mut all_tokens = TokenCounts::default();
    let mut all_cost = 0.0;
    for s in summaries {
        all_tokens.merge(&s.total_tokens);
        all_cost += s.total_cost;
    }

    let mut total_row = vec![
        Cell::new("TOTAL")
            .add_attribute(Attribute::Bold)
            .fg(Color::Yellow),
    ];
    if has_slugs {
        total_row.push(Cell::new(""));
    }
    total_row.extend([
        Cell::new(format!("{} sessions", summaries.len())).add_attribute(Attribute::Bold),
        Cell::new(""),
        Cell::new(""),
        Cell::new(fmt_tokens(all_tokens.total_tokens()))
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold),
    ]);
    if !cfg.no_cost {
        total_row.push(
            Cell::new(fmt_cost(all_cost))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold)
                .fg(Color::Green),
        );
    }
    table.add_row(total_row);

    println!("{table}");
    if summaries.len() > limit {
        println!("  ... showing {}/{} sessions", limit, summaries.len());
    }
}

// ─── Blocks ──────────────────────────────────────────

pub fn print_block_table(summaries: &[BlockSummary], cfg: &OutputConfig) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    if cfg.csv {
        let show_thinking = summaries.iter().any(|s| s.total_tokens.thinking_tokens > 0);
        if cfg.no_cost {
            if show_thinking {
                println!("Block Start,Block End,Input,Output,Thinking,Total");
            } else {
                println!("Block Start,Block End,Input,Output,Total");
            }
        } else if show_thinking {
            println!("Block Start,Block End,Input,Output,Thinking,Total,Cost");
        } else {
            println!("Block Start,Block End,Input,Output,Total,Cost");
        }
        for s in summaries {
            print!(
                "{},{},{},{}",
                s.block_start.format("%Y-%m-%d %H:%M"),
                s.block_end.format("%H:%M"),
                s.total_tokens.input_tokens,
                s.total_tokens.output_tokens,
            );
            if show_thinking {
                print!(",{}", s.total_tokens.thinking_tokens);
            }
            print!(",{}", s.total_tokens.total_tokens());
            if !cfg.no_cost {
                print!(",{:.6}", s.total_cost);
            }
            println!();
        }
        return;
    }

    let mut table = new_table(cfg);
    let mut header = vec![
        Cell::new("Block").add_attribute(Attribute::Bold),
        Cell::new("Input").add_attribute(Attribute::Bold),
        Cell::new("Output").add_attribute(Attribute::Bold),
        Cell::new("Total Tokens").add_attribute(Attribute::Bold),
    ];
    if !cfg.no_cost {
        header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
    }
    table.set_header(header);

    for s in summaries {
        let block_str = format!(
            "{} {}~{}",
            s.block_start.format("%m-%d"),
            s.block_start.format("%H:%M"),
            s.block_end.format("%H:%M"),
        );
        let mut row = vec![
            Cell::new(block_str),
            Cell::new(fmt_tokens(s.total_tokens.input_tokens)).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.output_tokens)).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.total_tokens())).set_alignment(CellAlignment::Right),
        ];
        if !cfg.no_cost {
            row.push(
                Cell::new(fmt_cost(s.total_cost))
                    .set_alignment(CellAlignment::Right)
                    .fg(Color::Green),
            );
        }
        table.add_row(row);
    }

    println!("{table}");
}

// ─── Instances ───────────────────────────────────────

pub fn print_instance_table(summaries: &[InstanceUsage], cfg: &OutputConfig) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    let limit = cfg.limit.unwrap_or(30);

    if cfg.csv {
        let show_thinking = summaries.iter().any(|s| s.total_tokens.thinking_tokens > 0);
        if cfg.no_cost {
            if show_thinking {
                println!("Project,Sessions,Thinking,Total Tokens");
            } else {
                println!("Project,Sessions,Total Tokens");
            }
        } else if show_thinking {
            println!("Project,Sessions,Thinking,Total Tokens,Cost");
        } else {
            println!("Project,Sessions,Total Tokens,Cost");
        }
        for s in summaries.iter().take(limit) {
            print!(
                "{},{}",
                csv_escape(&s.project),
                s.session_count,
            );
            if show_thinking {
                print!(",{}", s.total_tokens.thinking_tokens);
            }
            print!(",{}", s.total_tokens.total_tokens());
            if !cfg.no_cost {
                print!(",{:.6}", s.total_cost);
            }
            println!();
        }
        return;
    }

    let mut table = new_table(cfg);
    let mut header = vec![
        Cell::new("Project").add_attribute(Attribute::Bold),
        Cell::new("Sessions").add_attribute(Attribute::Bold),
        Cell::new("Total Tokens").add_attribute(Attribute::Bold),
    ];
    if !cfg.no_cost {
        header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
    }
    table.set_header(header);

    for s in summaries.iter().take(limit) {
        let mut row = vec![
            Cell::new(&s.project).fg(Color::Cyan),
            Cell::new(s.session_count).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.total_tokens()))
                .set_alignment(CellAlignment::Right),
        ];
        if !cfg.no_cost {
            row.push(
                Cell::new(fmt_cost(s.total_cost))
                    .set_alignment(CellAlignment::Right)
                    .fg(Color::Green),
            );
        }
        table.add_row(row);
    }

    // Grand total row (sum of ALL instances)
    let mut all_tokens = TokenCounts::default();
    let mut all_cost = 0.0;
    let mut all_sessions = 0usize;
    for s in summaries {
        all_tokens.merge(&s.total_tokens);
        all_cost += s.total_cost;
        all_sessions += s.session_count;
    }

    let mut total_row = vec![
        Cell::new("TOTAL")
            .add_attribute(Attribute::Bold)
            .fg(Color::Yellow),
        Cell::new(all_sessions)
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold),
        Cell::new(fmt_tokens(all_tokens.total_tokens()))
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold),
    ];
    if !cfg.no_cost {
        total_row.push(
            Cell::new(fmt_cost(all_cost))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold)
                .fg(Color::Green),
        );
    }
    table.add_row(total_row);

    println!("{table}");
    if summaries.len() > limit {
        println!("  ... showing {}/{} projects", limit, summaries.len());
    }
}

// ─── Statusline ──────────────────────────────────────

pub fn print_statusline(blocks: &[BlockSummary], tz: &Option<String>, offset_hours: i64) {
    use chrono::Timelike;

    // Use local timezone for current time calculation
    let now_local = if let Some(tz_str) = tz {
        if let Ok(tz) = tz_str.parse::<chrono_tz::Tz>() {
            chrono::Utc::now().with_timezone(&tz).naive_local()
        } else {
            chrono::Local::now().naive_local()
        }
    } else {
        chrono::Local::now().naive_local()
    };

    // Apply offset: shift current time to find which block we're in
    let shifted = now_local - chrono::Duration::hours(offset_hours);
    let hour_block = (shifted.hour() / 5) * 5;

    let block_start_local = shifted
        .date()
        .and_hms_opt(hour_block, 0, 0)
        .unwrap()
        + chrono::Duration::hours(offset_hours);

    // Find the block that contains "now" based on local time mapping
    // Since blocks are stored in UTC, we need to find the right one
    let current = blocks.iter().find(|b| {
        let b_local = if let Some(tz_str) = tz {
            if let Ok(tz) = tz_str.parse::<chrono_tz::Tz>() {
                b.block_start.with_timezone(&tz).naive_local()
            } else {
                chrono::DateTime::<chrono::Local>::from(b.block_start).naive_local()
            }
        } else {
            chrono::DateTime::<chrono::Local>::from(b.block_start).naive_local()
        };
        b_local == block_start_local
    });

    match current {
        Some(block) => {
            let block_idx = (shifted.hour() / 5) + 1; // 1-indexed
            let total_blocks = 24u32.div_ceil(5); // 5
            let input = fmt_tokens_compact(block.total_tokens.input_tokens);
            let output = fmt_tokens_compact(block.total_tokens.output_tokens);
            println!(
                "↑{} ↓{} {} [{}/{}h]",
                input,
                output,
                fmt_cost(block.total_cost),
                block_idx,
                total_blocks,
            );
        }
        None => {
            // No usage in current block
            println!("↑0 ↓0 $0.00 [0/5h]");
        }
    }
    // No debug output — statusline should be silent on stderr
}

// ─── Session Detail ──────────────────────────────────

pub fn print_session_detail(session: &SessionUsage, cfg: &OutputConfig) {
    // Header info
    println!("Session: {}", session.session_id);
    if let Some(ref slug) = session.slug {
        println!("Slug:    {}", slug);
    }
    println!(
        "Date:    {}",
        session.date.format("%Y-%m-%d")
    );
    println!(
        "Duration: {}",
        fmt_duration(session.first_activity, session.last_activity)
    );
    if let Some(ref project) = session.project {
        println!("Project: {}", project);
    }
    if session.fast_entry_count > 0 {
        println!("Mode:    fast ({} entries)", session.fast_entry_count);
    }
    println!(
        "Total:   {} tokens",
        fmt_tokens(session.total_tokens.total_tokens())
    );
    if !cfg.no_cost {
        println!("Cost:    {}", fmt_cost(session.total_cost));
    }
    println!();

    // Per-model breakdown table
    let mut table = new_table(cfg);
    let mut header = vec![
        Cell::new("Model").add_attribute(Attribute::Bold),
        Cell::new("Input").add_attribute(Attribute::Bold),
        Cell::new("Output").add_attribute(Attribute::Bold),
        Cell::new("Cache Write").add_attribute(Attribute::Bold),
        Cell::new("Cache Read").add_attribute(Attribute::Bold),
    ];
    if !cfg.no_cost {
        header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
    }
    table.set_header(header);

    let mut models: Vec<_> = session.by_model.iter().collect();
    models.sort_by(|a, b| {
        b.1.cost
            .total()
            .partial_cmp(&a.1.cost.total())
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    for (model, usage) in &models {
        let mut row = vec![
            Cell::new(model).fg(Color::Cyan),
            Cell::new(fmt_tokens(usage.tokens.input_tokens)).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(usage.tokens.output_tokens)).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(usage.tokens.cache_creation_tokens()))
                .set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(usage.tokens.cache_read_tokens))
                .set_alignment(CellAlignment::Right),
        ];
        if !cfg.no_cost {
            row.push(
                Cell::new(fmt_cost(usage.cost.total()))
                    .set_alignment(CellAlignment::Right)
                    .fg(Color::Green),
            );
        }
        table.add_row(row);
    }

    println!("{table}");
}

// ─── Agent ───────────────────────────────────────────

pub fn print_agent_table(summaries: &[SessionAgentSummary], cfg: &OutputConfig) {
    if summaries.is_empty() {
        println!("No sessions with sub-agents found.");
        return;
    }

    let limit = cfg.limit.unwrap_or(30);

    if cfg.csv {
        if cfg.no_cost {
            println!("Session,Slug,Project,Agents");
        } else {
            println!("Session,Slug,Project,Agents,Agent Cost,Agent %");
        }
        for s in summaries.iter().take(limit) {
            let short_id = &s.session_id[..8.min(s.session_id.len())];
            let agent_count = s.agents.iter().filter(|a| a.agent_id.is_some()).count();
            let agent_cost: f64 = s
                .agents
                .iter()
                .filter(|a| a.agent_id.is_some())
                .map(|a| a.cost)
                .sum();
            let agent_pct = if s.total_cost > 0.0 {
                (agent_cost / s.total_cost) * 100.0
            } else {
                0.0
            };
            print!(
                "{},{},{},{}",
                short_id,
                csv_escape(s.slug.as_deref().unwrap_or("-")),
                csv_escape(s.project.as_deref().unwrap_or("-")),
                agent_count,
            );
            if !cfg.no_cost {
                print!(",{:.6},{:.1}", agent_cost, agent_pct);
            }
            println!();
        }
        return;
    }

    let mut table = new_table(cfg);
    let mut header = vec![
        Cell::new("Session").add_attribute(Attribute::Bold),
        Cell::new("Slug").add_attribute(Attribute::Bold),
        Cell::new("Project").add_attribute(Attribute::Bold),
        Cell::new("Agents").add_attribute(Attribute::Bold),
    ];
    if !cfg.no_cost {
        header.push(Cell::new("Agent Cost").add_attribute(Attribute::Bold));
        header.push(Cell::new("Agent %").add_attribute(Attribute::Bold));
    }
    table.set_header(header);

    for s in summaries.iter().take(limit) {
        let short_id = &s.session_id[..8.min(s.session_id.len())];
        let agent_count = s.agents.iter().filter(|a| a.agent_id.is_some()).count();
        let agent_cost: f64 = s
            .agents
            .iter()
            .filter(|a| a.agent_id.is_some())
            .map(|a| a.cost)
            .sum();
        let agent_pct = if s.total_cost > 0.0 {
            (agent_cost / s.total_cost) * 100.0
        } else {
            0.0
        };

        let slug_display = s
            .slug
            .as_deref()
            .map(|sl| truncate_str(sl, 25))
            .unwrap_or_else(|| "-".to_string());

        let mut row = vec![
            Cell::new(short_id).fg(Color::Cyan),
            Cell::new(slug_display),
            Cell::new(s.project.as_deref().unwrap_or("-")),
            Cell::new(agent_count).set_alignment(CellAlignment::Right),
        ];
        if !cfg.no_cost {
            row.push(
                Cell::new(fmt_cost(agent_cost))
                    .set_alignment(CellAlignment::Right)
                    .fg(Color::Green),
            );
            row.push(
                Cell::new(format!("{:.1}%", agent_pct))
                    .set_alignment(CellAlignment::Right),
            );
        }
        table.add_row(row);
    }

    println!("{table}");
    if summaries.len() > limit {
        println!(
            "  ... showing {}/{} sessions with agents",
            limit,
            summaries.len()
        );
    }
}

pub fn print_agent_detail(summary: &SessionAgentSummary, cfg: &OutputConfig) {
    // Header info
    println!("Session: {}", summary.session_id);
    if let Some(ref slug) = summary.slug {
        println!("Slug:    {}", slug);
    }
    if let Some(ref project) = summary.project {
        println!("Project: {}", project);
    }
    if !cfg.no_cost {
        println!("Total:   {}", fmt_cost(summary.total_cost));
    }
    println!();

    // Per-agent breakdown table
    let mut table = new_table(cfg);
    let mut header = vec![
        Cell::new("Agent").add_attribute(Attribute::Bold),
        Cell::new("Model").add_attribute(Attribute::Bold),
        Cell::new("Entries").add_attribute(Attribute::Bold),
        Cell::new("Total Tokens").add_attribute(Attribute::Bold),
    ];
    if !cfg.no_cost {
        header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
        header.push(Cell::new("Cost %").add_attribute(Attribute::Bold));
    }
    table.set_header(header);

    for agent in &summary.agents {
        let agent_label = match &agent.agent_id {
            None => "(main)".to_string(),
            Some(id) => {
                let short = &id[..8.min(id.len())];
                short.to_string()
            }
        };

        let mut row = vec![
            Cell::new(&agent_label).fg(if agent.agent_id.is_none() {
                Color::Yellow
            } else {
                Color::Cyan
            }),
            Cell::new(agent.model.as_deref().unwrap_or("-")),
            Cell::new(agent.entry_count).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(agent.tokens.total_tokens()))
                .set_alignment(CellAlignment::Right),
        ];
        if !cfg.no_cost {
            row.push(
                Cell::new(fmt_cost(agent.cost))
                    .set_alignment(CellAlignment::Right)
                    .fg(Color::Green),
            );
            row.push(
                Cell::new(format!("{:.1}%", agent.cost_pct))
                    .set_alignment(CellAlignment::Right),
            );
        }
        table.add_row(row);
    }

    println!("{table}");
}

// ─── JSON ────────────────────────────────────────────

pub fn print_json(result: &crate::types::AggregationResult) {
    let json = serde_json::to_string_pretty(result).unwrap();
    println!("{json}");
}
