//! Environment-driven configuration. Matches Python version's `AUTO_SURVEY_*` env vars.

use std::env;

#[derive(Debug, Clone)]
pub struct Settings {
    pub sqlite_path: String,

    pub llm_backend: String,
    pub llm_model: String,
    pub litellm_base_url: String,
    pub litellm_api_key: String,

    pub min_delay: u64,
    pub max_delay: u64,
    pub concurrency: usize,
    pub time_budget_secs: u64,
    pub headless: bool,

    pub camoufox_cli: String,
    pub camoufox_profile: String,
    pub playwright_cli: String,
    pub pw_profile_dir: String,

    pub execution_hour: u32,

    pub web_port: u16,
    pub bark_device_key: String,
    pub bark_server: String,

    pub line_community_name: String,
    pub line_enabled: bool,
    pub line_scroll_pages: u32,

    pub ocr_url: String,
}

fn env_or(key: &str, default: &str) -> String {
    env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_parse<T: std::str::FromStr>(key: &str, default: T) -> T {
    env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

fn env_bool(key: &str, default: bool) -> bool {
    env::var(key)
        .ok()
        .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(default)
}

impl Settings {
    pub fn from_env() -> Self {
        Self {
            sqlite_path: env_or("AUTO_SURVEY_SQLITE_PATH", "data/auto_survey.db"),

            llm_backend: env_or("AUTO_SURVEY_LLM_BACKEND", "litellm"),
            llm_model: env_or("AUTO_SURVEY_LLM_MODEL", "grok-4.1-fast"),
            litellm_base_url: env_or("AUTO_SURVEY_LITELLM_BASE_URL", "http://localhost:4000/v1"),
            litellm_api_key: env_or("AUTO_SURVEY_LITELLM_API_KEY", "sk-litellm-local-dev"),

            min_delay: env_parse("AUTO_SURVEY_MIN_DELAY", 5),
            max_delay: env_parse("AUTO_SURVEY_MAX_DELAY", 15),
            concurrency: env_parse("AUTO_SURVEY_CONCURRENCY", 12usize),
            time_budget_secs: env_parse("AUTO_SURVEY_TIME_BUDGET", 300u64),
            headless: env_bool("AUTO_SURVEY_HEADLESS", true),

            camoufox_cli: env_or("AUTO_SURVEY_CAMOUFOX_CLI", "camoufox-cli"),
            camoufox_profile: env_or(
                "AUTO_SURVEY_CAMOUFOX_PROFILE",
                "~/.camoufox-profiles/master",
            ),
            playwright_cli: env_or("AUTO_SURVEY_PLAYWRIGHT_CLI", "playwright-cli"),
            pw_profile_dir: env_or("AUTO_SURVEY_PW_PROFILE_DIR", ""),

            execution_hour: env_parse("AUTO_SURVEY_EXECUTION_HOUR", 14),

            web_port: env_parse("AUTO_SURVEY_WEB_PORT", 10300),
            bark_device_key: env_or("AUTO_SURVEY_BARK_DEVICE_KEY", "gx7KnK5f8iAKuqNLWzy5hP"),
            bark_server: env_or("AUTO_SURVEY_BARK_SERVER", "http://localhost:8090"),

            line_community_name: env_or("AUTO_SURVEY_LINE_COMMUNITY_NAME", "微光早餐會"),
            line_enabled: env_bool("AUTO_SURVEY_LINE_ENABLED", true),
            line_scroll_pages: env_parse("AUTO_SURVEY_LINE_SCROLL_PAGES", 3),

            ocr_url: env_or("AUTO_SURVEY_OCR_URL", "http://127.0.0.1:10202"),
        }
    }
}
