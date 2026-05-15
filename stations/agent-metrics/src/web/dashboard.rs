//! Dashboard HTML — render the same Jinja2 template the Python version used.
//!
//! The template only references `{{ version }}` and `{{ url_for(...) }}` style
//! placeholders that we map manually since minijinja doesn't ship `url_for`.
//!
//! # Fallback strategy
//!
//! `CARGO_MANIFEST_DIR` is baked in at compile time and may point to a
//! temporary worktree that no longer exists at runtime.  To guard against
//! "Template missing", `include_str!` embeds `templates/index.html` directly
//! into the binary.  Disk read is still attempted first so that dev-mode edits
//! to the template take effect on service restart without a recompile.

use super::AppState;
use axum::{extract::State, response::Html};
use minijinja::{context, Environment};
use std::sync::OnceLock;

// Compile-time fallback — the binary is always self-contained regardless of
// whether the build worktree still exists at runtime.
const EMBEDDED_INDEX_HTML: &str = include_str!("../../templates/index.html");

static ENV: OnceLock<Environment<'static>> = OnceLock::new();

fn load_template_body(state: &AppState) -> String {
    let template_path = std::path::Path::new(&state.settings.templates_dir).join("index.html");
    match std::fs::read_to_string(&template_path) {
        Ok(body) => body,
        Err(e) => {
            tracing::warn!(
                path = %template_path.display(),
                error = %e,
                "templates_dir read failed; falling back to embedded index.html"
            );
            EMBEDDED_INDEX_HTML.to_string()
        }
    }
}

fn env_for(state: &AppState) -> &'static Environment<'static> {
    ENV.get_or_init(|| {
        let mut env = Environment::new();
        let body = load_template_body(state);
        // Strip any FastAPI-specific {{ url_for(...) }} expressions so the
        // template renders cleanly under minijinja with the absolute /static URLs.
        let cleaned = body.replace("{{ request.url_for('static', path='", "/static")
                          .replace("') }}", "");
        let leaked: &'static str = Box::leak(cleaned.into_boxed_str());
        env.add_template("index", leaked).expect("index template");
        env
    })
}

pub async fn index(State(state): State<AppState>) -> Html<String> {
    let env = env_for(&state);
    let template = env.get_template("index").expect("index template");
    let version = env!("CARGO_PKG_VERSION");
    let body = template
        .render(context! { version => version })
        .unwrap_or_else(|e| format!("template render error: {e}"));
    Html(body)
}
