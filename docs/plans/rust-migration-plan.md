# Workshop Rust 遷移計畫

> 制定日期：2026-04-17
> 目標：將 Workshop 從 Python 逐步遷移到 Rust（主）/ Go（輔），僅保留載入 MLX 模型的 5 個 Python worker。

## 背景

- 40 個 Python 常駐程序佔用 ~1.4GB RAM（Python runtime 每程序 ~25MB）
- 真正需要 Python 的只有 5 個直接載入 MLX 模型的 worker（~5K 行）
- 其餘 95% 程式碼的「AI 依賴」本質是 HTTP/gRPC/subprocess 呼叫，語言無關
- Rust binary ~2-3MB/程序，零 GC，長期執行 RSS 不膨脹

## 最終目標架構

```
┌─────────────────────────────────────────────────────────┐
│                     Rust Layer                          │
│                                                         │
│  workshop-core         (axum, port 10000)               │
│    17 domain modules — auth, memvault, docvault, etc.   │
│    shared: DB pool, event bus, embedding bridge,        │
│           qdrant client, redis cache                    │
│                                                         │
│  station-infra         (axum, multi-port)               │
│    sentinel, system-monitor, hook-observatory,          │
│    agent-metrics, fleet, scheduler                      │
│                                                         │
│  station-tools         (axum, multi-port)               │
│    translate, tmux-webui, capture-console, video-edit,  │
│    ocr, auto-survey, anvil                              │
│                                                         │
│  station-session       (axum, multi-port)               │
│    session-channel, session-intelligence,               │
│    session-pipeline, session-redactor, session-archiver │
│                                                         │
│  mcp-unified           (stdin JSON-RPC, 1 binary)       │
│    所有 23 MCP server tools 合併                        │
│                                                         │
│  workshop-services     (程序管理器)                      │
│  hook-dispatcher       (Go, Claude Code hooks)          │
├─────────────────────────────────────────────────────────┤
│                    Python Layer (僅 AI)                  │
│                                                         │
│  embed_worker.py       — MLX Qwen3-Embedding (subprocess)│
│  rerank_worker.py      — MLX Jina Reranker (subprocess) │
│  stt station           — MLX Whisper (uvicorn)          │
│  tts station           — MLX F5-TTS/CosyVoice (uvicorn)│
│  vision station        — MLX MiniCPM-V (uvicorn)       │
│  LiteLLM               — 第三方 proxy (不動)            │
└─────────────────────────────────────────────────────────┘
```

### 最終狀態預估

| 層 | 程序數 | RSS |
|---|--------|-----|
| Rust (workshop-core + 3 station binaries + mcp-unified + workshop-services) | 6 | ~55MB |
| Go (hook-dispatcher) | 1 | ~5MB |
| Python AI workers | 5 | ~200MB |
| Python LiteLLM | 1 | ~50MB |
| **合計** | **13** | **~310MB** |

vs 現狀：40 程序，~1.4GB → **省 ~1.1GB，程序數降 68%**

---

## Rust 技術棧

| 用途 | Crate | 備註 |
|------|-------|------|
| HTTP framework | `axum` 0.8+ | tokio 團隊，生態最活躍 |
| Async runtime | `tokio` | 業界標準 |
| DB | `sqlx` 0.8+ | 編譯期 SQL 檢查，async PostgreSQL |
| DB migration | `sqlx migrate` | 取代 Alembic |
| 序列化 | `serde` + `serde_json` | 零成本抽象 |
| HTTP client | `reqwest` | 呼叫 LiteLLM/AI workers |
| Qdrant | `qdrant-client` | 官方 Rust SDK |
| Redis | `redis` crate + `deadpool-redis` | cache + event bus |
| OpenAPI | `utoipa` + `utoipa-swagger-ui` | 自動生成 |
| 錯誤處理 | `anyhow` + `thiserror` | |
| 日誌 | `tracing` + `tracing-subscriber` | 結構化日誌 |
| CLI | `clap` | 取代 argparse |
| MCP protocol | 自實作 | stdin/stdout JSON-RPC（已驗證） |
| subprocess | `tokio::process` | 呼叫 embed_worker/rerank_worker |
| 測試 | `tokio::test` + `sqlx::test` | |

### Python ↔ Rust 互動

| 介面 | 用途 | 延遲 |
|------|------|------|
| HTTP localhost | Rust → Python AI workers (stt/tts/vision) | ~1ms |
| subprocess stdin/stdout | Rust → embed_worker / rerank_worker | ~μs (IPC) |
| gRPC | Rust → Qdrant | ~1ms |
| HTTP localhost:4000 | Rust → LiteLLM → external LLM | ~100ms+ |

---

## 遷移階段

### Phase 0：基礎設施（已完成 ✅）

| 項目 | 狀態 | 說明 |
|------|------|------|
| Go mcp-lazy-wrapper | ✅ 完成 | 15 on-demand MCP server 節省 376MB |
| Memory Guardian 在場感知 | ✅ 完成 | Chrome 分層管理 + HIDIdleTime 偵測 |

---

### Phase 1：Hook Dispatcher → Go（高頻，體感最明顯）

**目標**：消除每次 Claude Code tool call 的 ~50-150ms Python import 延遲

**範圍**：
- `~/.claude/hooks/dispatcher.py` → Go binary
- `~/workshop/stations/hook-observatory/handlers/*.py` (19 handlers) → Go

**關鍵 handlers（高頻）**：
| Handler | 觸發時機 | 作用 |
|---------|---------|------|
| bash_safety.py | 每次 Bash tool call | regex 檢查危險指令 |
| secret_scan.py | git push 時 | regex 掃描 secrets |
| session_cost.py | 每次 response | JSONL 記錄費用 |
| context_supervisor.py | SessionStart | context 注入 |
| pm_autopilot.py | SessionStart | GitHub issue 注入 |

**架構**：
```
hook-dispatcher (Go binary, ~5MB)
├── main.go          — 讀 stdin JSON, route by event_type
├── registry.go      — handler 註冊表
├── bash_safety.go   — regex 指令驗證
├── secret_scan.go   — regex secret 掃描
├── session_cost.go  — JSONL atomic append
├── context.go       — context 注入 (讀檔 + JSON 合併)
└── pm_autopilot.go  — GitHub API 呼叫 (gh CLI subprocess)
```

**預估**：
- 工時：30-40hr
- 效果：tool call 延遲降低 ~50-150ms
- 風險：低（可逐個 handler 遷移，Python 作 fallback）

**驗證**：
```bash
# 比較 hook latency
time echo '{"event":"PreToolUse","tool":"Bash"}' | python3 dispatcher.py
time echo '{"event":"PreToolUse","tool":"Bash"}' | ./hook-dispatcher
```

---

### Phase 2：MCP Unified Server → Rust

**目標**：23 個 MCP server 合併成 1 個 Rust binary

**範圍**：
- `~/workshop/mcp/*/server.py` (23 servers, ~7K 行)
- `~/workshop/libs/sdk-client/` (38 API clients, ~13K 行) → Rust crate `workshop-sdk`

**架構**：
```
mcp-unified (Rust binary, ~10MB)
├── src/
│   ├── main.rs           — stdin JSON-RPC dispatcher
│   ├── protocol.rs       — MCP JSON-RPC 實作
│   ├── sdk/
│   │   ├── mod.rs
│   │   ├── client.rs     — BaseClient (reqwest)
│   │   ├── memvault.rs   — 17 tools
│   │   ├── taskflow.rs   — 12 tools
│   │   ├── finance.rs    — 10 tools
│   │   └── ...           — 其他 module clients
│   └── tools/
│       ├── mod.rs         — tool registry
│       ├── memvault.rs    — tool handlers
│       └── ...
├── Cargo.toml
└── tools_manifest.json   — 靜態 tool 清單
```

**預估**：
- 工時：60-80hr
- RAM：23 servers (654MB + 74MB wrapper) → 1 binary (~15MB) = **省 713MB**
- 風險：中（需要正確實作 MCP protocol + 所有 tool 參數）
- Go lazy-wrapper 不再需要

**驗證**：
```bash
# MCP protocol 測試
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | ./mcp-unified
# 逐一比對每個 tool 的 input/output 與 Python 版本
```

---

### Phase 3：Stations 合併 → Rust

**目標**：20+ 個 Python station 合併成 3 個 Rust binary

**分批策略**（按風險排序，先做低風險的）：

#### Phase 3a：station-tools（最簡單）
| Station | 行數 | 本質 |
|---------|------|------|
| translate | 1,173 | HTTP proxy → DeepL/Google API |
| capture-console | 463 | HTTP proxy → Core capture API |
| tmux-webui | 1,791 | WebSocket + tmux subprocess |
| video-edit | 2,342 | CLI wrapper → ffmpeg subprocess |
| sandbox-executor | 162 | subprocess 執行器 |
| scheduler | 276 | Cronicle API proxy |
| ocr | 1,428 | subprocess → tesseract |

**工時**：40-60hr
**省下**：7 programs × ~25MB = ~175MB → 1 program ~8MB = **省 ~167MB**

#### Phase 3b：station-session
| Station | 行數 | 本質 |
|---------|------|------|
| session-channel | 1,028 | SSE + Redis pub/sub |
| session-intelligence | 430 | 統計查詢 |
| session-pipeline | 1,122 | Pipeline orchestration |
| session-redactor | 237 | Regex 替換 |
| session-archiver | 3,843 | DB 歸檔 + 壓縮 |

**工時**：40-50hr
**省下**：5 programs → 1 program = **省 ~100MB**

#### Phase 3c：station-infra（最複雜）
| Station | 行數 | 複雜度 |
|---------|------|--------|
| sentinel | 4,231 | HTTP health checks + Playwright CLI subprocess |
| system-monitor | 4,735 | vm_stat/ps/ioreg 解析 + Guardian |
| hook-observatory | 9,656 | Hook 分析 + DB + LLM (HTTP) |
| agent-metrics | 8,119 | 指標收集 + DB + LLM (HTTP) |
| fleet | 2,352 | Windows dispatch + SSH |
| auto-survey | 3,384 | 問卷 + DB |
| anvil | 5,553 | Blueprint 執行 + DB |

**工時**：100-130hr
**省下**：7 programs → 1 program = **省 ~230MB**

---

### Phase 4：Workshop Core → Rust（最大重寫）

**目標**：FastAPI monolith (82K 行 Python) → axum monolith (Rust)

**前置條件**：
- Phase 2 的 `workshop-sdk` Rust crate 已穩定
- sqlx migration 體系建立
- shared/ 層的 Rust 等價物已驗證

**分批策略**（按模組大小，先做小的）：

#### Phase 4a：小模組（<2K 行，快速驗證 pattern）
| Module | Lines | 重點 |
|--------|-------|------|
| admin | 540 | 基礎 CRUD |
| ideagraph | 139 | 基礎 CRUD |
| matchcore | 147 | 基礎 CRUD |
| workpool | 122 | 基礎 CRUD |
| skillpath | 125 | 基礎 CRUD |
| assistant | 858 | HTTP→LiteLLM |

**目的**：建立 Rust 版 BaseCRUDService<T> pattern，驗證 sqlx + axum + serde 的 DX

**工時**：40-50hr

#### Phase 4b：中模組（2-6K 行）
| Module | Lines | 重點 |
|--------|-------|------|
| auth | 1,502 | Session + cookie + RBAC |
| invest | 1,170 | CRUD + events |
| taskflow | 1,445 | CRUD + events + dispatch |
| notification | 1,755 | Multi-channel push |
| briefing | 2,351 | HTTP→LiteLLM + template |
| nodeflow | 2,114 | DAG execution |
| intelflow | 2,737 | RSS + HTTP→LiteLLM |
| paper | 2,628 | HTTP→LiteLLM + storage |
| capture | 3,460 | HTTP→LiteLLM + enrich |
| finance | 5,791 | 複雜 CRUD + subscription |

**工時**：120-160hr

#### Phase 4c：大模組（>9K 行）
| Module | Lines | 重點 |
|--------|-------|------|
| dailyos | 9,053 | Ritual engine + method strategy |
| docvault | 13,055 | 文件管理 + embedding + RAG |
| memvault | 18,901 | 記憶體系 + KG + dream + CRAG |

**工時**：150-200hr

#### Phase 4d：shared/ 基礎層
| 檔案 | Rust 替代 |
|------|----------|
| database.py | sqlx connection pool |
| event_bus.py | tokio::broadcast + redis streams |
| embedding.py | reqwest + redis cache |
| omlx_bridge.py | tokio::process (stdin/stdout IPC) |
| rerank_bridge.py | tokio::process |
| qdrant_client.py | qdrant-client crate |
| qdrant_search.py | qdrant-client + custom scoring |
| redis.py | deadpool-redis |
| middleware.py | axum middleware layers |
| errors.py | thiserror hierarchy |
| schemas.py (Pydantic) | serde + utoipa |
| models.py (SQLAlchemy) | sqlx FromRow |

**工時**：60-80hr（先於 Phase 4a，作為基礎）

---

### Phase 5：收尾

| 項目 | 說明 |
|------|------|
| workshop_services.py → Rust/Go | 程序管理器 |
| Cronicle runners → Rust CLI | 隨 Core 遷移後自然跟隨 |
| Alembic → sqlx migrate | DB migration 體系切換 |
| SDK client Python → 棄用 | 被 Rust crate 取代 |
| mcp-lazy-wrapper (Go) → 棄用 | 被 mcp-unified (Rust) 取代 |
| Python mcp-lazy-wrapper.py → 刪除 | 被 Go 版取代，Go 版又被 Rust 取代 |

---

## 總工時估算

| Phase | 範圍 | 工時 | 累計省 RAM |
|-------|------|------|-----------|
| 0 | ✅ lazy-wrapper + guardian | 2hr (done) | 376MB |
| 1 | hook-dispatcher (Go) | 30-40hr | +0MB (latency 改善) |
| 2 | MCP unified (Rust) | 60-80hr | +713MB = 1,089MB |
| 3a | station-tools (Rust) | 40-60hr | +167MB = 1,256MB |
| 3b | station-session (Rust) | 40-50hr | +100MB = 1,356MB |
| 3c | station-infra (Rust) | 100-130hr | +230MB = 1,586MB |
| 4-shared | shared/ 基礎層 (Rust) | 60-80hr | — |
| 4a | 小模組 (Rust) | 40-50hr | — |
| 4b | 中模組 (Rust) | 120-160hr | — |
| 4c | 大模組 (Rust) | 150-200hr | +60MB = 1,646MB |
| 5 | 收尾 | 20-30hr | — |
| **合計** | | **660-880hr** | **~1.1GB** |

## 風險與緩解

| 風險 | 嚴重度 | 緩解 |
|------|--------|------|
| Rust 編譯慢影響開發 | 中 | `cargo watch` + incremental build，底層改動少 |
| sqlx 沒有 Alembic 的 autogenerate | 中 | 手寫 SQL migration，配合 `sqlx prepare` 離線檢查 |
| MCP protocol 邊界案例 | 低 | Go wrapper 已驗證 protocol，Rust 直接移植 |
| Python AI worker IPC 斷線 | 低 | tokio::process 自動重啟 + healthcheck |
| 遷移期間兩套並行 | 中 | 每個 phase 獨立，隨時可回 Python 版 |

## 重要原則

1. **蠶食式**：每次改一個 service，跑穩再下一個，隨時可停
2. **HTTP 邊界**：Rust service 和 Python AI worker 之間永遠是 HTTP，不用 FFI
3. **向後相容**：每個 phase 完成後，對外 API contract 不變
4. **先 shared/ 後 modules**：Phase 4 開始前，shared/ 基礎層必須先穩定
5. **測試驅動**：每個 Rust service 必須有 integration test 對比 Python 版的 output
6. **Alembic 最後遷移**：在所有模組都改完之前，Alembic 仍然可用（sqlx 可讀同一個 DB）
