//! Ad-hoc runner: invoke line::fetch_latest_survey_urls and print detected URLs.
//!
//! Usage (scroll up N pages):
//!   cargo run --release --example line_fetch -- 5
//!
//! Prints each SurveyCake URL on its own line. Extra diagnostics go to stderr.

use auto_survey::{config::Settings, line};

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let scroll_pages: u32 = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(3);

    let cfg = Settings::from_env();
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .expect("reqwest client");

    eprintln!(
        "[line_fetch] community='{}' scroll_pages={} ocr_url={}",
        cfg.line_community_name, scroll_pages, cfg.ocr_url
    );

    let urls = line::fetch_latest_survey_urls(&cfg, &client, scroll_pages).await;

    eprintln!("[line_fetch] found {} unique URLs", urls.len());
    for u in &urls {
        println!("{}", u);
    }

    if urls.is_empty() {
        std::process::exit(1);
    }
}
