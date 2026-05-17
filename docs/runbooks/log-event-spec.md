# Log Event Spec — 跨語言 Log 合約

> **Schema 位置**: `schemas/log-event.schema.json` (JSON Schema draft-07)

---

## 動機

Workshop 同時運行 Python（core）、Rust（sentinel binary）、Go（hook-dispatcher）三種語言的服務。
為了讓 `request_id` 能跨服務邊界串接同一次請求的完整 log 鏈路，**所有服務必須輸出完全一致的欄位名**（尤其是 `ts`、`level`、`logger`、`msg`、`service`、`request_id`）。

---

## 完整欄位表

| 欄位名 | 型別 | 必填 | 範例 |
|--------|------|------|------|
| `ts` | string (ISO 8601 + tz) | ✅ | `2026-05-17T14:30:00.123+08:00` |
| `level` | string (enum) | ✅ | `INFO` |
| `logger` | string (dotted) | ✅ | `core.finance.services` |
| `msg` | string | ✅ | `Transaction created` |
| `service` | string | ✅ | `core` |
| `request_id` | string (12-hex) | — | `01abcdef1234` |
| `user_id` | string \| null | — | `018e1f2a-3b4c-...` |
| `space_id` | string \| null | — | `018e1f2a-0000-...` |
| `module` | string | — | `finance` |
| `duration_ms` | number | — | `45.2` |
| `status_code` | integer | — | `200` |
| `method` | string (HTTP verb) | — | `POST` |
| `path` | string | — | `/api/finance/transactions` |
| `traceback` | string | — | `Traceback (most recent...` |
| `error_type` | string | — | `ConnectionRefusedError` |
| `extra` | object | — | `{"feed_id": "abc123"}` |

`level` 允許值：`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`

---

## Python 實作範例

使用 `python-json-logger`，透過 `rename_fields` 將 Python 預設欄位名對映到合約欄位名。

```python
import logging
from pythonjsonlogger import jsonlogger

def get_logger(name: str, service: str = "core") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={
                "asctime": "ts",
                "levelname": "level",
                "name": "logger",
                "message": "msg",
            },
            datefmt="%Y-%m-%dT%H:%M:%S.%f%z",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

# 使用範例
log = get_logger("core.finance.services")

log.info(
    "Transaction created",
    extra={
        "service": "core",
        "module": "finance",
        "request_id": request_id,
        "user_id": str(current_user.id),
        "duration_ms": elapsed_ms,
        "status_code": 201,
        "method": "POST",
        "path": "/api/finance/transactions",
    },
)
```

**安裝**：`uv add python-json-logger`

---

## Rust 實作範例

使用 `tracing` + `tracing-subscriber` 的 JSON layer。欄位名需透過 `rename_fields` 或 `event_format` 對映。

```rust
use tracing_subscriber::{fmt, layer::SubscriberExt, util::SubscriberInitExt};
use std::time::SystemTime;

pub fn init_tracing(service: &'static str) {
    let json_layer = fmt::layer()
        .json()
        .with_timer(fmt::time::SystemTime)
        .with_target(true)          // maps to `logger`
        .with_current_span(false);

    tracing_subscriber::registry()
        .with(json_layer)
        .init();

    // service 欄位透過 span 注入，避免每個 event 都手動帶
    tracing::info!(service = service, "tracing initialized");
}

// 使用範例（在 axum middleware 中）
pub async fn log_request(request_id: &str, path: &str) {
    tracing::info!(
        request_id = %request_id,
        path = %path,
        service = "sentinel",
        "Health check started"
    );
}

// 錯誤範例
tracing::error!(
    error_type = "ConnectionRefusedError",
    request_id = %rid,
    "Health check failed"
);
```

**Cargo.toml 依賴**:
```toml
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["json", "env-filter"] }
```

---

## Go 實作範例

使用標準庫 `log/slog`（Go 1.21+），JSON handler 直接輸出 JSON。注意 Go 的預設鍵名需手動對映。

```go
package logger

import (
    "log/slog"
    "os"
)

func New(service string) *slog.Logger {
    handler := slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
        Level: slog.LevelInfo,
        // 自訂 key 名以符合合約（ts/level/msg）
        ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
            switch a.Key {
            case slog.TimeKey:
                a.Key = "ts"
            case slog.LevelKey:
                a.Key = "level"
            case slog.MessageKey:
                a.Key = "msg"
            case slog.SourceKey:
                a.Key = "logger"
            }
            return a
        },
    })
    return slog.New(handler).With("service", service)
}

// 使用範例（hook-dispatcher）
var log = logger.New("hook-dispatcher")

func handleRequest(requestID, path string) {
    log.Info("Request received",
        slog.String("request_id", requestID),
        slog.String("path", path),
        slog.String("method", "POST"),
    )
}

// 錯誤範例
log.Error("Dispatch failed",
    slog.String("request_id", rid),
    slog.String("error_type", "TimeoutError"),
    slog.String("logger", "hook-dispatcher.router"),
)
```

---

## request_id 傳遞約定

- **起源**：前端（workbench）在每次 HTTP 請求發起時生成，格式為 12 位 lowercase hex（48-bit ms timestamp，UUID v7 time portion，time-sortable）
- **HTTP Header**：`X-Request-ID: 01abcdef1234`
- **傳遞鏈**：
  ```
  前端 → Nginx (透傳) → core (FastAPI middleware 注入 request_id) → 下游 MCP/service (透過 HTTP header 轉發)
  ```
- **Python 中間件**：從 `request.headers.get("X-Request-ID")` 讀取，透過 `contextvars.ContextVar` 傳至同一 request 的所有 log call
- **Go/Rust**：從 context 或 span 攜帶，每個 log call 帶入 `request_id = %rid`
- **缺失時**：log `request_id` 欄位省略，不填 `""` 或 `null`

---

## 驗證指令

### JSON 語法驗證（本機必有 jq）

```bash
# 確認 schema 本身合法
jq . schemas/log-event.schema.json > /dev/null && echo "OK"

# 快速驗一筆 log event（必填欄位是否齊全）
echo '{"ts":"2026-05-17T14:30:00.123+08:00","level":"INFO","logger":"core.finance.services","msg":"ok","service":"core"}' \
  | jq 'if (.ts and .level and .logger and .msg and .service) then "PASS" else "FAIL" end'
```

### Schema 驗證（需安裝 ajv-cli）

```bash
# 安裝（一次性）
npm install -g ajv-cli

# 驗一筆 log event JSON 是否符合 schema
ajv validate -s schemas/log-event.schema.json -d /tmp/sample-log-event.json

# 驗 Python json-logger 輸出流（tail 截段後驗）
tail -n 100 /var/log/workshop/core.log \
  | jq -c 'select(.level == "ERROR")' \
  | while read line; do
      echo "$line" > /tmp/event.json
      ajv validate -s schemas/log-event.schema.json -d /tmp/event.json
    done
```

---

## 相關檔案

- `schemas/log-event.schema.json` — 機器可讀合約（本文件的 source of truth）
- `core/src/shared/logging.py` — Python 統一 logger factory（待建）
- `stations/hook-dispatcher/logger/` — Go logger package（待建）
- `stations/sentinel/src/telemetry/` — Rust tracing 初始化（待建）
