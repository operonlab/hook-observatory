mod engine;
mod llm;
mod parsing;
mod sandbox;
mod types;

use clap::Parser;
use types::{Context, RlmConfig};

#[derive(Parser)]
#[command(name = "rlm", about = "Recursive Language Model engine (Rust)")]
struct Cli {
    /// Query / prompt to answer
    prompt: String,

    /// Context: file path or "-" for stdin
    #[arg(short, long)]
    context: Option<String>,

    /// Treat context as chunks separated by this delimiter
    #[arg(long, default_value = "")]
    chunk_delimiter: String,

    /// Model for main loop
    #[arg(long, default_value = "sonnet")]
    model: String,

    /// Model for sub-LLM calls
    #[arg(long, default_value = "haiku")]
    sub_model: String,

    /// Max recursion depth
    #[arg(long, default_value = "2")]
    max_depth: u32,

    /// Max iterations per depth level
    #[arg(long, default_value = "20")]
    max_iterations: u32,

    /// Timeout in seconds
    #[arg(long, default_value = "300")]
    timeout: f64,

    /// Verbose logging to stderr
    #[arg(short, long)]
    verbose: bool,

    /// OpenAI-compatible API base URL (e.g. http://localhost:4000/v1)
    #[arg(long)]
    api_base: Option<String>,

    /// API key for the above
    #[arg(long)]
    api_key: Option<String>,

    /// Output format: text or json
    #[arg(long, default_value = "text")]
    output: String,
}

#[tokio::main]
async fn main() {
    let _log_guard = workshop_log::init("rlm");
    let cli = Cli::parse();

    // Read context
    let context = if let Some(ctx_path) = &cli.context {
        let content = if ctx_path == "-" {
            use std::io::Read;
            let mut buf = String::new();
            std::io::stdin().read_to_string(&mut buf).unwrap();
            buf
        } else {
            std::fs::read_to_string(ctx_path).unwrap_or_else(|e| {
                eprintln!("Error reading context file: {e}");
                std::process::exit(1);
            })
        };

        if !cli.chunk_delimiter.is_empty() {
            let chunks: Vec<String> = content
                .split(&cli.chunk_delimiter)
                .map(|s| s.to_string())
                .collect();
            Some(Context::Chunks(chunks))
        } else {
            Some(Context::Single(content))
        }
    } else {
        None
    };

    let config = RlmConfig {
        model: cli.model,
        sub_model: cli.sub_model,
        max_depth: cli.max_depth,
        max_iterations: cli.max_iterations,
        max_timeout_secs: cli.timeout,
        verbose: cli.verbose,
        api_base: cli.api_base,
        api_key: cli.api_key,
        ..Default::default()
    };

    let mut engine = engine::RlmEngine::new(config, 0);
    let result = engine.completion(&cli.prompt, context.as_ref()).await;

    match cli.output.as_str() {
        "json" => {
            println!("{}", serde_json::to_string_pretty(&result).unwrap());
        }
        _ => {
            println!("{}", result.response);
            if cli.verbose {
                eprintln!("---");
                eprintln!("Status: {}", result.status);
                eprintln!("Iterations: {}", result.iterations);
                eprintln!("LLM calls: {}", result.usage.total_calls);
                eprintln!("Time: {:.1}s", result.execution_time_secs);
            }
        }
    }
}
