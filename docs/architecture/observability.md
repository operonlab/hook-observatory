---
doc_version: 2
content_hash: ad0b7cdb
source_version: 2
target_lang: zh-TW
translated_at: 2026-02-23
---

# 可觀測性架構

## 策略

透過 **OpenTelemetry** 作為通用儀表化層，利用三大支柱（追蹤、指標、日誌）實現全面可觀測性。

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

## 環境策略

### 開發環境：grafana/otel-lgtm（單一容器）

一個 Docker 容器即可提供完整的 LGTM 堆疊：

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

**為何開發環境使用單一容器：**
- 零配置，執行 `docker compose up` 即可運作
- 所有後端均已預先連接至 Grafana
- 內建 OTel Collector，隨時準備接收 OTLP
- 足夠輕量，適合本地開發

### 生產環境：SigNoz

用於生產環境可觀測性的自代管 SigNoz：

```yaml
# infra/observability/signoz-values.yml (Helm chart or docker-compose)
# SigNoz provides:
# - ClickHouse for storage (traces, metrics, logs)
# - Query service
# - Frontend dashboard
# - OTel Collector
# - Alerting
```

**為何在生產環境選擇 SigNoz 而非完整 Grafana 堆疊：**
- 單一平台整合所有三種信號（無需分開維護 Tempo/Loki/Prometheus）
- 基於 ClickHouse 構建（日誌查詢效能優於 Loki）
- 原生支援 OpenTelemetry（從一開始就圍繞 OTLP設計）
- 跨信號的統一警示
- 自代管，無供應商鎖定

## 應用程式整合

### FastAPI 儀表化

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

### 使用 structlog + OTel 的結構化日誌

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

日誌輸出：
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

## 事件驅動 + OTel 整合

每個透過 Event Bus 發布的事件都會建立一個 OTel span 並更新指標：

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

### 追蹤傳播

事件攜帶 `trace_id` 以維持跨非同步邊界的追蹤連續性：

```
HTTP Request (trace A)
    → Module publishes event (span in trace A)
        → Subscriber handles event (new span, linked to trace A via event.trace_id)
            → Subscriber publishes follow-up event (still in trace A)
```

## 儀表板設計

### 核心儀表板：系統健康狀況

| 面板 | 指標 | 用途 |
|-------|--------|---------|
| 請求率 | `http.server.request.duration` | 整體 API 吞吐量 |
| 錯誤率 | `http.server.request.duration{http.status_code>=400}` | API 錯誤百分比 |
| P50/P95/P99 延遲 | `http.server.request.duration` histogram | 回應時間分佈 |
| 活躍會話 | `auth.sessions.active` gauge | 當前登入用戶 |

### 事件儀表板：事件流

| 面板 | 指標 | 用途 |
|-------|--------|---------|
| 事件吞吐量 | `events.published.total` by type | 每秒每種類型的事件數 |
| 事件處理延遲 | `events.handling.duration_ms` | 處理器耗時 |
| 事件錯誤率 | `events.handling.errors` | 失敗的事件處理器 |
| 事件流程圖 | Trace waterfall | 視覺化事件鏈 |
| 熱門事件類型 | `events.published.total` ranked | 哪些事件觸發最頻繁 |

### 模組儀表板：各模組健康狀況

| 面板 | 指標 | 用途 |
|-------|--------|---------|
| 模組請求率 | `http.server.request.duration{http.route~"/api/<module>/*"}` | 各模組吞吐量 |
| 模組錯誤率 | Same, filtered by status code | 各模組錯誤 |
| 資料庫查詢延遲 | `db.client.operation.duration` by module schema | 查詢效能 |
| 快取命中率 | `redis.cache.hit / (hit + miss)` | 快取有效性 |

### 插件儀表板：插件健康狀況

| 面板 | 指標 | 用途 |
|-------|--------|---------|
| Hook 執行次數 | `plugin.hook.executions` by plugin | 插件活動 |
| Hook 延遲 | `plugin.hook.duration_ms` | 插件效能影響 |
| Hook 拒絕 | `plugin.hook.rejections` | 插件阻斷行為 |
| 權限遭拒 | `plugin.permission.denied` | 權限配置錯誤 |

## 配置

### 應用程式環境變數

```bash
# OTel Collector 端點
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# 服務識別
OTEL_SERVICE_NAME=core
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=development

# 日誌層級
LOG_LEVEL=info
```

### OTel Collector 配置（生產環境）

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

## 警示規則（生產環境）

| 警示 | 條件 | 嚴重程度 |
|-------|-----------|----------|
| 高錯誤率 | `error_rate > 5%` 持續 5 分鐘 | 危急 |
| 高延遲 | `p99 > 2s` 持續 5 分鐘 | 警告 |
| 事件總線待處理積壓 | `pending_events > 1000` | 警告 |
| 插件 Hook 超時 | `hook.duration > 5s` | 警告 |
| 資料庫連接池耗盡 | `pool.available == 0` | 危急 |
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
