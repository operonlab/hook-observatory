---
doc_version: 2
content_hash: ad0b7cdb
source_version: 2
target_lang: en
translated_at: 2026-02-24
source_hash: c3f21f17
source_lang: zh-TW
---

# Observability Architecture

## Strategy

Achieve comprehensive observability through **OpenTelemetry** as a universal instrumentation layer, leveraging the three pillars (traces, metrics, logs).

```
┌─────────────────────────────────────────────────┐
│               Application Layer                  │
│                                                  │
│  FastAPI + structlog ──► OTel SDK                │
│  Event Bus ──► OTel Spans + Metrics              │
│  httpx ──► OTel HTTP Instrumentation             │
│  psycopg ──► OTel DB Instrumentation             │
└──────────────────────┬──────────────────────────┘
                       │ OTLP (gRPC/HTTP)
                       ▼
              ┌──────────────────┐
              │  OTel Collector  │
              └────────┬─────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │  Traces  │ │ Metrics  │ │   Logs   │
    │  (Tempo) │ │ (Prom.)  │ │  (Loki)  │
    └──────────┘ └──────────┘ └──────────┘
          │            │            │
          └────────────┼────────────┘
                       ▼
              ┌──────────────────┐
              │    Grafana       │
              │   Dashboards     │
              └──────────────────┘
```

## Environment Strategy

### Development Environment: grafana/otel-lgtm (Single Container)

A single Docker container provides the complete LGTM stack:

```yaml
# infra/docker/docker-compose.dev.yml
services:
  otel-lgtm:
    image: grafana/otel-lgtm:latest
    ports:
      - "3100:3100"   # Loki (logs)
      - "4317:4317"   # OTLP gRPC
      - "4318:4318"   # OTLP HTTP
      - "9090:9090"   # Prometheus (metrics)
      - "3200:3200"   # Tempo (traces)
      - "3000:3000"   # Grafana (dashboards)
    environment:
      - ENABLE_LOGS_ALL=true
```

**Why use a single container for the development environment:**
- Zero-configuration, runs with just `docker compose up`
- All backends are pre-connected to Grafana
- Built-in OTel Collector, ready to receive OTLP
- Sufficiently lightweight, suitable for local development

### Production Environment: SigNoz

Self-hosted SigNoz for production observability:

```yaml
# infra/observability/signoz-values.yml (Helm chart or docker-compose)
# SigNoz provides:
# - ClickHouse for storage (traces, metrics, logs)
# - Query service
# - Frontend dashboard
# - OTel Collector
# - Alerting
```

**Why choose SigNoz over the full Grafana stack for production:**
- Single platform integrates all three signals (no need to maintain Tempo/Loki/Prometheus separately)
- Built on ClickHouse (log query performance is superior to Loki)
- Native OpenTelemetry support (designed around OTLP from the start)
- Unified alerting across signals
- Self-hosted, no vendor lock-in

## Application Integration

### FastAPI Instrumentation

```python
# core/src/observability.py
from opentelemetry import trace, metrics
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource

def setup_observability(app: FastAPI, service_name: str = "core"):
    resource = Resource.create({"service.name": service_name})

    # Traces
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    # Auto-instrumentation
    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    PsycopgInstrumentor().instrument()

    # Metrics
    meter_provider = MeterProvider(resource=resource)
    metrics.set_meter_provider(meter_provider)
```

### Structured Logging with structlog + OTel

```python
import structlog
from opentelemetry import trace

def setup_logging():
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            add_otel_context,        # Inject trace_id, span_id
            structlog.processors.JSONRenderer(),
        ],
    )

def add_otel_context(logger, method_name, event_dict):
    """Inject OpenTelemetry trace context into log records."""
    span = trace.get_current_span()
    if span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict
```

Log Output:
```json
{
  "event": "transaction.created",
  "level": "info",
  "timestamp": "2026-02-22T10:30:00Z",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "user_id": "usr_456",
  "amount": 150.00
}
```

## Event-Driven + OTel Integration

Each event published via the Event Bus creates an OTel span and updates metrics:

```python
class OTelEventMiddleware(EventMiddleware):
    def __init__(self):
        self.tracer = trace.get_tracer("event_bus")
        meter = metrics.get_meter("event_bus")
        self.event_counter = meter.create_counter(
            "events.published.total",
            description="Total events published",
        )
        self.event_latency = meter.create_histogram(
            "events.handling.duration_ms",
            description="Event handling duration in milliseconds",
        )

    async def __call__(self, event: Event, next: Callable):
        self.event_counter.add(1, {"event.type": event.type, "event.source": event.source})

        with self.tracer.start_as_current_span(
            f"event:{event.type}",
            attributes={
                "event.id": event.id,
                "event.type": event.type,
                "event.source": event.source,
                "user.id": event.user_id or "",
            },
        ):
            start = time.monotonic()
            await next(event)
            duration_ms = (time.monotonic() - start) * 1000
            self.event_latency.record(duration_ms, {"event.type": event.type})
```

### Trace Propagation

Events carry a `trace_id` to maintain trace continuity across asynchronous boundaries:

```
HTTP Request (trace A)
    → Module publishes event (span in trace A)
        → Subscriber handles event (new span, linked to trace A via event.trace_id)
            → Subscriber publishes follow-up event (still in trace A)
```

## Dashboard Design

### Core Dashboard: System Health

| Panel | Metric | Purpose |
|-------|--------|---------|
| Request Rate | `http.server.request.duration` | Overall API throughput |
| Error Rate | `http.server.request.duration{http.status_code>=400}` | API error percentage |
| P50/P95/P99 Latency | `http.server.request.duration` histogram | Response time distribution |
| Active Sessions | `auth.sessions.active` gauge | Currently logged-in users |

### Event Dashboard: Event Flow

| Panel | Metric | Purpose |
|-------|--------|---------|
| Event Throughput | `events.published.total` by type | Events per second by type |
| Event Handling Latency | `events.handling.duration_ms` | Processor time consumption |
| Event Error Rate | `events.handling.errors` | Failed event handlers |
| Event Flow Diagram | Trace waterfall | Visualize event chains |
| Top Event Types | `events.published.total` ranked | Which events are triggered most frequently |

### Module Dashboard: Health by Module

| Panel | Metric | Purpose |
|-------|--------|---------|
| Module Request Rate | `http.server.request.duration{http.route~"/api/<module>/*"}` | Throughput per module |
| Module Error Rate | Same, filtered by status code | Errors per module |
| Database Query Latency | `db.client.operation.duration` by module schema | Query performance |
| Cache Hit Rate | `redis.cache.hit / (hit + miss)` | Cache effectiveness |

### Plugin Dashboard: Plugin Health

| Panel | Metric | Purpose |
|-------|--------|---------|
| Hook Executions | `plugin.hook.executions` by plugin | Plugin activity |
| Hook Latency | `plugin.hook.duration_ms` | Plugin performance impact |
| Hook Rejections | `plugin.hook.rejections` | Plugin blocking behavior |
| Permission Denied | `plugin.permission.denied` | Permission configuration errors |

## Configuration

### Application Environment Variables

```bash
# OTel Collector Endpoint
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Service Identification
OTEL_SERVICE_NAME=core
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=development

# Log Level
LOG_LEVEL=info
```

### OTel Collector Configuration (Production)

```yaml
# infra/observability/otel-collector.yml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 1000

exporters:
  otlp/signoz:
    endpoint: signoz-otel-collector:4317
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/signoz]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/signoz]
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/signoz]
```

## Alerting Rules (Production)

| Alert | Condition | Severity |
|-------|-----------|----------|
| High Error Rate | `error_rate > 5%` for 5 minutes | Critical |
| High Latency | `p99 > 2s` for 5 minutes | Warning |
| Event Bus Pending Backlog | `pending_events > 1000` | Warning |
| Plugin Hook Timeout | `hook.duration > 5s` | Warning |
| Database Connection Pool Exhausted | `pool.available == 0` | Critical |
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3086ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2439ms
