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

/// Print daily summaries as a table
pub fn print_daily_table(summaries: &[DailySummary], breakdown: bool) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    if breakdown {
        print_daily_breakdown(summaries);
        return;
    }

    let mut table = Table::new();
    table.load_preset(UTF8_FULL_CONDENSED);
    table.set_header(vec![
        Cell::new("Date").add_attribute(Attribute::Bold),
        Cell::new("Input").add_attribute(Attribute::Bold),
        Cell::new("Output").add_attribute(Attribute::Bold),
        Cell::new("Cache Write").add_attribute(Attribute::Bold),
        Cell::new("Cache Read").add_attribute(Attribute::Bold),
        Cell::new("Total Tokens").add_attribute(Attribute::Bold),
        Cell::new("Cost").add_attribute(Attribute::Bold),
    ]);

    let mut grand_tokens = TokenCounts::default();
    let mut grand_cost = 0.0;

    for s in summaries {
        table.add_row(vec![
            Cell::new(s.date.format("%Y-%m-%d").to_string()),
            Cell::new(fmt_tokens(s.total_tokens.input_tokens)).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.output_tokens)).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.cache_creation_tokens))
                .set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.cache_read_tokens))
                .set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.total_tokens()))
                .set_alignment(CellAlignment::Right),
            Cell::new(fmt_cost(s.total_cost))
                .set_alignment(CellAlignment::Right)
                .fg(Color::Green),
        ]);
        grand_tokens.merge(&s.total_tokens);
        grand_cost += s.total_cost;
    }

    // Total row
    table.add_row(vec![
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
        Cell::new(fmt_cost(grand_cost))
            .set_alignment(CellAlignment::Right)
            .add_attribute(Attribute::Bold)
            .fg(Color::Green),
    ]);

    println!("{table}");
}

fn print_daily_breakdown(summaries: &[DailySummary]) {
    let mut table = Table::new();
    table.load_preset(UTF8_FULL_CONDENSED);
    table.set_header(vec![
        Cell::new("Date").add_attribute(Attribute::Bold),
        Cell::new("Model").add_attribute(Attribute::Bold),
        Cell::new("Input").add_attribute(Attribute::Bold),
        Cell::new("Output").add_attribute(Attribute::Bold),
        Cell::new("Cache Write").add_attribute(Attribute::Bold),
        Cell::new("Cache Read").add_attribute(Attribute::Bold),
        Cell::new("Cost").add_attribute(Attribute::Bold),
    ]);

    for s in summaries {
        let mut models: Vec<_> = s.by_model.iter().collect();
        models.sort_by(|a, b| b.1.cost.total().partial_cmp(&a.1.cost.total()).unwrap());

        for (i, (model, usage)) in models.iter().enumerate() {
            let date_str = if i == 0 {
                s.date.format("%Y-%m-%d").to_string()
            } else {
                String::new()
            };

            table.add_row(vec![
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
                Cell::new(fmt_cost(usage.cost.total()))
                    .set_alignment(CellAlignment::Right)
                    .fg(Color::Green),
            ]);
        }
    }

    println!("{table}");
}

/// Print monthly summaries
pub fn print_monthly_table(summaries: &[MonthlySummary], breakdown: bool) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    let mut table = Table::new();
    table.load_preset(UTF8_FULL_CONDENSED);

    if breakdown {
        table.set_header(vec![
            Cell::new("Month").add_attribute(Attribute::Bold),
            Cell::new("Model").add_attribute(Attribute::Bold),
            Cell::new("Input").add_attribute(Attribute::Bold),
            Cell::new("Output").add_attribute(Attribute::Bold),
            Cell::new("Cache Write").add_attribute(Attribute::Bold),
            Cell::new("Cache Read").add_attribute(Attribute::Bold),
            Cell::new("Cost").add_attribute(Attribute::Bold),
        ]);

        for s in summaries {
            let mut models: Vec<_> = s.by_model.iter().collect();
            models.sort_by(|a, b| b.1.cost.total().partial_cmp(&a.1.cost.total()).unwrap());

            for (i, (model, usage)) in models.iter().enumerate() {
                let month_str = if i == 0 {
                    format!("{}-{:02}", s.year, s.month)
                } else {
                    String::new()
                };

                table.add_row(vec![
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
                    Cell::new(fmt_cost(usage.cost.total()))
                        .set_alignment(CellAlignment::Right)
                        .fg(Color::Green),
                ]);
            }
        }
    } else {
        table.set_header(vec![
            Cell::new("Month").add_attribute(Attribute::Bold),
            Cell::new("Input").add_attribute(Attribute::Bold),
            Cell::new("Output").add_attribute(Attribute::Bold),
            Cell::new("Cache Write").add_attribute(Attribute::Bold),
            Cell::new("Cache Read").add_attribute(Attribute::Bold),
            Cell::new("Total Tokens").add_attribute(Attribute::Bold),
            Cell::new("Cost").add_attribute(Attribute::Bold),
        ]);

        let mut grand_tokens = TokenCounts::default();
        let mut grand_cost = 0.0;

        for s in summaries {
            table.add_row(vec![
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
                Cell::new(fmt_cost(s.total_cost))
                    .set_alignment(CellAlignment::Right)
                    .fg(Color::Green),
            ]);
            grand_tokens.merge(&s.total_tokens);
            grand_cost += s.total_cost;
        }

        table.add_row(vec![
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
            Cell::new(fmt_cost(grand_cost))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold)
                .fg(Color::Green),
        ]);
    }

    println!("{table}");
}

/// Print weekly summaries
pub fn print_weekly_table(summaries: &[WeeklySummary], breakdown: bool) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    let mut table = Table::new();
    table.load_preset(UTF8_FULL_CONDENSED);

    if breakdown {
        table.set_header(vec![
            Cell::new("Week").add_attribute(Attribute::Bold),
            Cell::new("Model").add_attribute(Attribute::Bold),
            Cell::new("Input").add_attribute(Attribute::Bold),
            Cell::new("Output").add_attribute(Attribute::Bold),
            Cell::new("Cost").add_attribute(Attribute::Bold),
        ]);

        for s in summaries {
            let mut models: Vec<_> = s.by_model.iter().collect();
            models.sort_by(|a, b| b.1.cost.total().partial_cmp(&a.1.cost.total()).unwrap());

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

                table.add_row(vec![
                    Cell::new(week_str),
                    Cell::new(model).fg(Color::Cyan),
                    Cell::new(fmt_tokens(usage.tokens.input_tokens))
                        .set_alignment(CellAlignment::Right),
                    Cell::new(fmt_tokens(usage.tokens.output_tokens))
                        .set_alignment(CellAlignment::Right),
                    Cell::new(fmt_cost(usage.cost.total()))
                        .set_alignment(CellAlignment::Right)
                        .fg(Color::Green),
                ]);
            }
        }
    } else {
        table.set_header(vec![
            Cell::new("Week").add_attribute(Attribute::Bold),
            Cell::new("Input").add_attribute(Attribute::Bold),
            Cell::new("Output").add_attribute(Attribute::Bold),
            Cell::new("Cache Write").add_attribute(Attribute::Bold),
            Cell::new("Cache Read").add_attribute(Attribute::Bold),
            Cell::new("Total Tokens").add_attribute(Attribute::Bold),
            Cell::new("Cost").add_attribute(Attribute::Bold),
        ]);

        let mut grand_tokens = TokenCounts::default();
        let mut grand_cost = 0.0;

        for s in summaries {
            table.add_row(vec![
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
                Cell::new(fmt_cost(s.total_cost))
                    .set_alignment(CellAlignment::Right)
                    .fg(Color::Green),
            ]);
            grand_tokens.merge(&s.total_tokens);
            grand_cost += s.total_cost;
        }

        table.add_row(vec![
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
            Cell::new(fmt_cost(grand_cost))
                .set_alignment(CellAlignment::Right)
                .add_attribute(Attribute::Bold)
                .fg(Color::Green),
        ]);
    }

    println!("{table}");
}

/// Print session summaries
pub fn print_session_table(summaries: &[SessionUsage]) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    let mut table = Table::new();
    table.load_preset(UTF8_FULL_CONDENSED);
    table.set_header(vec![
        Cell::new("Session").add_attribute(Attribute::Bold),
        Cell::new("Date").add_attribute(Attribute::Bold),
        Cell::new("Project").add_attribute(Attribute::Bold),
        Cell::new("Total Tokens").add_attribute(Attribute::Bold),
        Cell::new("Cost").add_attribute(Attribute::Bold),
    ]);

    // Top 30 sessions by cost
    for s in summaries.iter().take(30) {
        let short_id = &s.session_id[..8.min(s.session_id.len())];
        table.add_row(vec![
            Cell::new(short_id).fg(Color::Cyan),
            Cell::new(s.date.format("%Y-%m-%d").to_string()),
            Cell::new(s.project.as_deref().unwrap_or("-")),
            Cell::new(fmt_tokens(s.total_tokens.total_tokens()))
                .set_alignment(CellAlignment::Right),
            Cell::new(fmt_cost(s.total_cost))
                .set_alignment(CellAlignment::Right)
                .fg(Color::Green),
        ]);
    }

    println!("{table}");
    if summaries.len() > 30 {
        println!("  ... and {} more sessions", summaries.len() - 30);
    }
}

/// Print block summaries
pub fn print_block_table(summaries: &[BlockSummary]) {
    if summaries.is_empty() {
        println!("No data found for the specified date range.");
        return;
    }

    let mut table = Table::new();
    table.load_preset(UTF8_FULL_CONDENSED);
    table.set_header(vec![
        Cell::new("Block").add_attribute(Attribute::Bold),
        Cell::new("Input").add_attribute(Attribute::Bold),
        Cell::new("Output").add_attribute(Attribute::Bold),
        Cell::new("Total Tokens").add_attribute(Attribute::Bold),
        Cell::new("Cost").add_attribute(Attribute::Bold),
    ]);

    for s in summaries {
        let block_str = format!(
            "{} {}~{}",
            s.block_start.format("%m-%d"),
            s.block_start.format("%H:%M"),
            s.block_end.format("%H:%M"),
        );
        table.add_row(vec![
            Cell::new(block_str),
            Cell::new(fmt_tokens(s.total_tokens.input_tokens)).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.output_tokens)).set_alignment(CellAlignment::Right),
            Cell::new(fmt_tokens(s.total_tokens.total_tokens())).set_alignment(CellAlignment::Right),
            Cell::new(fmt_cost(s.total_cost))
                .set_alignment(CellAlignment::Right)
                .fg(Color::Green),
        ]);
    }

    println!("{table}");
}

/// Print any aggregation result as JSON
pub fn print_json(result: &crate::types::AggregationResult) {
    let json = serde_json::to_string_pretty(result).unwrap();
    println!("{json}");
}
