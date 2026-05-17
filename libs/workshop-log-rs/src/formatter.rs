use chrono::SecondsFormat;
use tracing::{Event, Subscriber};
use tracing_subscriber::layer::Context;
use tracing_subscriber::registry::LookupSpan;
use tracing_subscriber::Layer;

pub struct WorkshopJsonLayer<W> {
    service: &'static str,
    writer: std::sync::Mutex<W>,
}

impl<W: std::io::Write> WorkshopJsonLayer<W> {
    pub fn new(service: &'static str, writer: W) -> Self {
        Self {
            service,
            writer: std::sync::Mutex::new(writer),
        }
    }
}

impl<S, W> Layer<S> for WorkshopJsonLayer<W>
where
    S: Subscriber + for<'a> LookupSpan<'a>,
    W: std::io::Write + Send + 'static,
{
    fn on_event(&self, event: &Event<'_>, ctx: Context<'_, S>) {
        // 1. Collect fields from the event
        let mut visitor = FieldVisitor::default();
        event.record(&mut visitor);

        // 2. Walk parent spans for request_id / user_id / space_id
        let mut ctx_fields = serde_json::Map::new();
        if let Some(scope) = ctx.event_scope(event) {
            for span in scope.from_root() {
                let ext = span.extensions();
                if let Some(stored) = ext.get::<SpanFields>() {
                    for (k, v) in &stored.0 {
                        ctx_fields.entry(k.clone()).or_insert_with(|| v.clone());
                    }
                }
            }
        }

        // 3. Build JSON record aligned to log-event.schema.json
        let mut record = serde_json::Map::new();
        record.insert(
            "ts".into(),
            serde_json::Value::String(
                chrono::Local::now().to_rfc3339_opts(SecondsFormat::Millis, true),
            ),
        );
        // schema enum: DEBUG / INFO / WARNING / ERROR / CRITICAL
        // tracing levels: TRACE / DEBUG / INFO / WARN / ERROR
        let level_str = match *event.metadata().level() {
            tracing::Level::ERROR => "ERROR",
            tracing::Level::WARN => "WARNING",
            tracing::Level::INFO => "INFO",
            tracing::Level::DEBUG => "DEBUG",
            tracing::Level::TRACE => "DEBUG",
        };
        record.insert("level".into(), level_str.into());
        record.insert(
            "logger".into(),
            serde_json::Value::String(event.metadata().target().to_string()),
        );
        record.insert(
            "msg".into(),
            visitor
                .message
                .unwrap_or_else(|| event.metadata().name().to_string())
                .into(),
        );
        record.insert("service".into(), self.service.into());

        // Span context fields (request_id, user_id, space_id, …)
        for (k, v) in ctx_fields {
            record.insert(k, v);
        }
        // Event-level fields (overwrite span fields if same key)
        for (k, v) in visitor.fields {
            record.insert(k, v);
        }

        let line = serde_json::to_string(&record).unwrap_or_default();
        if let Ok(mut w) = self.writer.lock() {
            let _ = writeln!(w, "{}", line);
        }
    }

    fn on_new_span(
        &self,
        attrs: &tracing::span::Attributes<'_>,
        id: &tracing::span::Id,
        ctx: Context<'_, S>,
    ) {
        let mut visitor = FieldVisitor::default();
        attrs.record(&mut visitor);
        if let Some(span) = ctx.span(id) {
            span.extensions_mut().insert(SpanFields(visitor.fields));
        }
    }
}

// ── Field visitor ─────────────────────────────────────────────────────────────

#[derive(Default)]
pub(crate) struct FieldVisitor {
    pub message: Option<String>,
    pub fields: Vec<(String, serde_json::Value)>,
}

impl tracing::field::Visit for FieldVisitor {
    fn record_str(&mut self, field: &tracing::field::Field, value: &str) {
        if field.name() == "message" {
            self.message = Some(value.to_string());
        } else {
            self.fields
                .push((field.name().to_string(), value.into()));
        }
    }

    fn record_i64(&mut self, field: &tracing::field::Field, value: i64) {
        self.fields.push((field.name().to_string(), value.into()));
    }

    fn record_u64(&mut self, field: &tracing::field::Field, value: u64) {
        self.fields.push((field.name().to_string(), value.into()));
    }

    fn record_f64(&mut self, field: &tracing::field::Field, value: f64) {
        self.fields.push((field.name().to_string(), value.into()));
    }

    fn record_bool(&mut self, field: &tracing::field::Field, value: bool) {
        self.fields.push((field.name().to_string(), value.into()));
    }

    fn record_debug(&mut self, field: &tracing::field::Field, value: &dyn std::fmt::Debug) {
        if field.name() == "message" {
            self.message = Some(format!("{:?}", value));
        } else {
            self.fields.push((
                field.name().to_string(),
                format!("{:?}", value).into(),
            ));
        }
    }
}

// ── Span extension storage ────────────────────────────────────────────────────

pub(crate) struct SpanFields(pub Vec<(String, serde_json::Value)>);
