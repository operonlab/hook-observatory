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

    let mut table = new_table(cfg);
    let mut header = vec![
        Cell::new("Date").add_attribute(Attribute::Bold),
        Cell::new("Input").add_attribute(Attribute::Bold),
        Cell::new("Output").add_attribute(Attribute::Bold),
        Cell::new("Cache Write").add_attribute(Attribute::Bold),
        Cell::new("Cache Read").add_attribute(Attribute::Bold),
        Cell::new("Total Tokens").add_attribute(Attribute::Bold),
    ];
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
            Cell::new(fmt_tokens(s.total_tokens.cache_creation_tokens))
                .set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.cache_read_tokens))
                .set_alignment(CellAlignment::Right),
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
        Cell::new(fmt_tokens(grand_tokens.cache_creation_tokens))
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold),
        Cell::new(fmt_tokens(grand_tokens.cache_read_tokens))
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold),
        Cell::new(fmt_tokens(grand_tokens.total_tokens()))
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold),
    ];
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
                Cell::new(fmt_tokens(usage.tokens.cache_creation_tokens))
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
                        usage.tokens.cache_creation_tokens,
                        usage.tokens.cache_read_tokens,
                    );
                } else {
                    println!(
                        "{},{},{},{},{},{},{:.6}",
                        s.date.format("%Y-%m-%d"),
                        csv_escape(model),
                        usage.tokens.input_tokens,
                        usage.tokens.output_tokens,
                        usage.tokens.cache_creation_tokens,
                        usage.tokens.cache_read_tokens,
                        usage.cost.total(),
                    );
                }
            }
        }
    } else {
        if cfg.no_cost {
            println!("Date,Input,Output,Cache Write,Cache Read,Total");
        } else {
            println!("Date,Input,Output,Cache Write,Cache Read,Total,Cost");
        }
        for s in summaries {
            if cfg.no_cost {
                println!(
                    "{},{},{},{},{},{}",
                    s.date.format("%Y-%m-%d"),
                    s.total_tokens.input_tokens,
                    s.total_tokens.output_tokens,
                    s.total_tokens.cache_creation_tokens,
                    s.total_tokens.cache_read_tokens,
                    s.total_tokens.total_tokens(),
                );
            } else {
                println!(
                    "{},{},{},{},{},{},{:.6}",
                    s.date.format("%Y-%m-%d"),
                    s.total_tokens.input_tokens,
                    s.total_tokens.output_tokens,
                    s.total_tokens.cache_creation_tokens,
                    s.total_tokens.cache_read_tokens,
                    s.total_tokens.total_tokens(),
                    s.total_cost,
                );
            }
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
                    Cell::new(fmt_tokens(usage.tokens.cache_creation_tokens))
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
        let mut header = vec![
            Cell::new("Month").add_attribute(Attribute::Bold),
            Cell::new("Input").add_attribute(Attribute::Bold),
            Cell::new("Output").add_attribute(Attribute::Bold),
            Cell::new("Cache Write").add_attribute(Attribute::Bold),
            Cell::new("Cache Read").add_attribute(Attribute::Bold),
            Cell::new("Total Tokens").add_attribute(Attribute::Bold),
        ];
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
                Cell::new(fmt_tokens(s.total_tokens.cache_creation_tokens))
                    .set_alignment(CellAlignment::Right),
                Cell::new(fmt_tokens(s.total_tokens.cache_read_tokens))
                    .set_alignment(CellAlignment::Right),
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
            Cell::new(fmt_tokens(grand_tokens.cache_creation_tokens))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
            Cell::new(fmt_tokens(grand_tokens.cache_read_tokens))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
            Cell::new(fmt_tokens(grand_tokens.total_tokens()))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
        ];
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
                    usage.tokens.cache_creation_tokens,
                    usage.tokens.cache_read_tokens,
                );
                if !cfg.no_cost {
                    print!(",{:.6}", usage.cost.total());
                }
                println!();
            }
        }
    } else {
        if cfg.no_cost {
            println!("Month,Input,Output,Cache Write,Cache Read,Total");
        } else {
            println!("Month,Input,Output,Cache Write,Cache Read,Total,Cost");
        }
        for s in summaries {
            print!(
                "{}-{:02},{},{},{},{},{}",
                s.year,
                s.month,
                s.total_tokens.input_tokens,
                s.total_tokens.output_tokens,
                s.total_tokens.cache_creation_tokens,
                s.total_tokens.cache_read_tokens,
                s.total_tokens.total_tokens(),
            );
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
        let mut header = vec![
            Cell::new("Week").add_attribute(Attribute::Bold),
            Cell::new("Model").add_attribute(Attribute::Bold),
            Cell::new("Input").add_attribute(Attribute::Bold),
            Cell::new("Output").add_attribute(Attribute::Bold),
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
        let mut header = vec![
            Cell::new("Week").add_attribute(Attribute::Bold),
            Cell::new("Input").add_attribute(Attribute::Bold),
            Cell::new("Output").add_attribute(Attribute::Bold),
            Cell::new("Cache Write").add_attribute(Attribute::Bold),
            Cell::new("Cache Read").add_attribute(Attribute::Bold),
            Cell::new("Total Tokens").add_attribute(Attribute::Bold),
        ];
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
                Cell::new(fmt_tokens(s.total_tokens.cache_creation_tokens))
                    .set_alignment(CellAlignment::Right),
                Cell::new(fmt_tokens(s.total_tokens.cache_read_tokens))
                    .set_alignment(CellAlignment::Right),
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
            Cell::new(fmt_tokens(grand_tokens.cache_creation_tokens))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
            Cell::new(fmt_tokens(grand_tokens.cache_read_tokens))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
            Cell::new(fmt_tokens(grand_tokens.total_tokens()))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold),
        ];
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
            println!("Week Start,Week End,Model,Input,Output");
        } else {
            println!("Week Start,Week End,Model,Input,Output,Cost");
        }
        for s in summaries {
            for (model, usage) in &s.by_model {
                print!(
                    "{},{},{},{},{}",
                    s.week_start.format("%Y-%m-%d"),
                    s.week_end.format("%Y-%m-%d"),
                    csv_escape(model),
                    usage.tokens.input_tokens,
                    usage.tokens.output_tokens,
                );
                if !cfg.no_cost {
                    print!(",{:.6}", usage.cost.total());
                }
                println!();
            }
        }
    } else {
        if cfg.no_cost {
            println!("Week Start,Week End,Input,Output,Cache Write,Cache Read,Total");
        } else {
            println!("Week Start,Week End,Input,Output,Cache Write,Cache Read,Total,Cost");
        }
        for s in summaries {
            print!(
                "{},{},{},{},{},{},{}",
                s.week_start.format("%Y-%m-%d"),
                s.week_end.format("%Y-%m-%d"),
                s.total_tokens.input_tokens,
                s.total_tokens.output_tokens,
                s.total_tokens.cache_creation_tokens,
                s.total_tokens.cache_read_tokens,
                s.total_tokens.total_tokens(),
            );
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

    if cfg.csv {
        if cfg.no_cost {
            println!("Session,Date,Project,Total Tokens");
        } else {
            println!("Session,Date,Project,Total Tokens,Cost");
        }
        for s in summaries.iter().take(limit) {
            let short_id = &s.session_id[..8.min(s.session_id.len())];
            print!(
                "{},{},{},{}",
                short_id,
                s.date.format("%Y-%m-%d"),
                csv_escape(s.project.as_deref().unwrap_or("-")),
                s.total_tokens.total_tokens(),
            );
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
        Cell::new("Date").add_attribute(Attribute::Bold),
        Cell::new("Project").add_attribute(Attribute::Bold),
        Cell::new("Total Tokens").add_attribute(Attribute::Bold),
    ];
    if !cfg.no_cost {
        header.push(Cell::new("Cost").add_attribute(Attribute::Bold));
    }
    table.set_header(header);

    for s in summaries.iter().take(limit) {
        let short_id = &s.session_id[..8.min(s.session_id.len())];
        let mut row = vec![
            Cell::new(short_id).fg(Color::Cyan),
            Cell::new(s.date.format("%Y-%m-%d").to_string()),
            Cell::new(s.project.as_deref().unwrap_or("-")),
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

    println!("{table}");
    if summaries.len() > limit {
        println!("  ... and {} more sessions", summaries.len() - limit);
    }
}

// ─── Blocks ──────────────────────────────────────────

pub fn print_block_table(summaries: &[BlockSummary], cfg: &OutputConfig) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    if cfg.csv {
        if cfg.no_cost {
            println!("Block Start,Block End,Input,Output,Total");
        } else {
            println!("Block Start,Block End,Input,Output,Total,Cost");
        }
        for s in summaries {
            print!(
                "{},{},{},{},{}",
                s.block_start.format("%Y-%m-%d %H:%M"),
                s.block_end.format("%H:%M"),
                s.total_tokens.input_tokens,
                s.total_tokens.output_tokens,
                s.total_tokens.total_tokens(),
            );
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
        if cfg.no_cost {
            println!("Project,Sessions,Total Tokens");
        } else {
            println!("Project,Sessions,Total Tokens,Cost");
        }
        for s in summaries.iter().take(limit) {
            print!(
                "{},{},{}",
                csv_escape(&s.project),
                s.session_count,
                s.total_tokens.total_tokens(),
            );
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

    println!("{table}");
    if summaries.len() > limit {
        println!("  ... and {} more projects", summaries.len() - limit);
    }
}

// ─── Statusline ──────────────────────────────────────

pub fn print_statusline(blocks: &[BlockSummary], pricing: &crate::pricing::PricingTable) {
    use chrono::{Timelike, Utc};

    let now = Utc::now();
    let hour_block = (now.hour() / 5) * 5;
    let block_start = now
        .date_naive()
        .and_hms_opt(hour_block, 0, 0)
        .unwrap()
        .and_utc();

    // Find current block
    let current = blocks.iter().find(|b| b.block_start == block_start);

    match current {
        Some(block) => {
            let block_idx = (now.hour() / 5) + 1; // 1-indexed
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

    // Also print pricing sanity check to stderr for debugging
    if let Some(p) = pricing.get("claude-opus-4-6") {
        eprintln!(
            "  pricing: opus input=${:.0}/MTok output=${:.0}/MTok",
            p.input_cost_per_token * 1_000_000.0,
            p.output_cost_per_token * 1_000_000.0,
        );
    }
}

// ─── JSON ────────────────────────────────────────────

pub fn print_json(result: &crate::types::AggregationResult) {
    let json = serde_json::to_string_pretty(result).unwrap();
    println!("{json}");
}
