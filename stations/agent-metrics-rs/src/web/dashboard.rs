//! Dashboard HTML — render the same Jinja2 template the Python version used.
//!
//! The template only references `{{ version }}` and `{{ url_for(...) }}` style
//! placeholders that we map manually since minijinja doesn't ship `url_for`.

use super::AppState;
use axum::{extract::State, response::Html};
use minijinja::{context, Environment};
use std::sync::OnceLock;

static ENV: OnceLock<Environment<'static>> = OnceLock::new();

fn env_for(state: &AppState) -> &'static Environment<'static> {
    ENV.get_or_init(|| {
        let mut env = Environment::new();
        let template_path = std::path::Path::new(&state.settings.templates_dir).join("index.html");
        let body = std::fs::read_to_string(&template_path)
            .unwrap_or_else(|_| "<html><body>Template missing</body></html>".to_string());
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
