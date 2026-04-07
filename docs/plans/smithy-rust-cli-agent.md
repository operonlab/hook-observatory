# Smithy — 開源 Rust CLI Coding Agent 完整架構計畫

## Context

蠶食各家開源 CLI coding agent 最佳模式，打造一個**開源產品**：
- **OpenHarness** 的輕量 skill 系統（metadata 100tok + content 5KB 惰性注入）
- **Aider** 的 git-first（可插拔 edit format）+ repo-map
- **Goose** 的 agent loop 防爆設計（停止規則）
- **Claude Code** 的 context 壓縮 + hook 約定 + sub-agent + team agent
- **pi_agent_rust** 的 <100ms 啟動效能

**定位**：開源產品，非個人工具。架構以 contributor 體驗、模組化、可擴展為優先。

**命名**：~~Forge~~（致命衝突：antinomyhq/forge 同語言同用途、foundry-rs forge、forge.rust-lang.org）→ **Smithy**（鍛造工坊，craftsmanship 意象）

---

## 架構決策

### 1. Multi-crate Workspace

開源專案需要清晰 crate 邊界，contributor 可獨立理解單一 crate，各 crate 可獨立發布至 crates.io。

### 2. 自建 Provider Trait（非 Rig）

Rig 會搶走 agent loop 控制權，其 Tool trait（`call(String) -> String`）不匹配我們需要的結構化 JSON I/O。自建 ~1000 行，完全掌控 streaming/tool calling/retry。

### 3. 自足獨立

不依賴任何 workshop 基礎設施（mcpproxy、hook-observatory、claude -p）。任何人 `cargo install` 即可使用。

### 4. XDG 路徑

`~/.config/smithy/`、`~/.local/share/smithy/`，跨平台標準。

### 5. 雙授權

MIT + Apache-2.0（Rust 生態標準）。

---

## Crate 依賴 DAG

```
                        smithy-cli (binary)
                            │
                    smithy-agent (agent loop + sub-agent)
                   ╱        │        ╲
      smithy-provider  smithy-tools  smithy-skills
               │            │            │
      [reqwest+sse]  smithy-executor smithy-config
               │            │            │
               └── smithy-hooks  smithy-permissions
                        │         ╱
                   smithy-types (共享型別、errors、traits)
```

### Crate 職責

| Crate | 職責 | 可發布 |
|-------|------|:---:|
| `smithy-types` | 所有共享型別（Message, ToolCall, ToolResult, Usage, ContentBlock）+ LLM 型別（CompletionRequest/Response, StreamEvent）+ Error 階層（thiserror） | ✅ |
| `smithy-config` | TOML 設定載入、XDG 路徑、env vars、SMITHY.md 解析 | ✅ |
| `smithy-permissions` | 能力模型 Allow/Deny + glob pattern，三模式（default/auto/plan） | ✅ |
| `smithy-hooks` | 兩階段 hook dispatcher（critical + deferrable + 5s budget）、subprocess 執行 | ✅ |
| `smithy-provider` | Provider trait + Anthropic 實作 + OpenAI-compatible 實作 + retry middleware | ✅ |
| `smithy-executor` | 帶副作用的程式執行抽象（Bash sandbox、WebFetch SSRF 防護、file advisory locking） | ✅ |
| `smithy-tools` | Tool trait + ToolRegistry + 12 個內建工具 + agent_tool | ✅ |
| `smithy-mcp` | MCP 客戶端管理器（rmcp）、命名空間路由、server lifecycle | ✅ |
| `smithy-skills` | Skill 載入器（.md + YAML frontmatter）、metadata-first、keyword matching | ✅ |
| `smithy-agent` | AgentRunner trait、LlmAgentRunner（核心迴圈）、AgentSpawner、AgentHandle、ContextManager | ✅ |
| `smithy-cli` | Binary：clap CLI、interactive REPL、headless mode | ❌ |
| `smithy-test-kit` | MockProvider、RecordedProvider、fixture 載入、test assertions（dev-dep only） | ❌ |

---

## Provider 設計（自建，~1000 行）

### 核心 Trait

```rust
// smithy-provider/src/lib.rs

#[async_trait]
pub trait Provider: Send + Sync {
    fn name(&self) -> &str;
    fn model(&self) -> &str;
    fn context_window(&self) -> u32;

    /// 串流完成（主要介面）
    async fn stream(
        &self,
        request: CompletionRequest,
    ) -> Result<StreamHandle, ProviderError>;

    /// 非串流完成（預設呼叫 stream 再 collect）
    async fn complete(
        &self,
        request: CompletionRequest,
    ) -> Result<CompletionResponse, ProviderError> {
        self.stream(request).await?.collect().await
    }

    /// 近似 token 計數
    fn estimate_tokens(&self, messages: &[Message]) -> u32 {
        // 預設 chars/4
    }
}
```

### StreamEvent + StreamHandle

```rust
pub enum StreamEvent {
    TextDelta(String),                    // 即時輸出到終端
    ToolUseStart { id: String, name: String },
    ToolUseDelta { id: String, delta: String },  // JSON 片段累積
    ToolUseEnd { id: String, input: serde_json::Value },
    Usage(TokenUsage),
    Done { stop_reason: StopReason },
    Error(ProviderError),
}

pub struct StreamHandle {
    rx: mpsc::Receiver<StreamEvent>,
    cancel: CancellationToken,
}

impl StreamHandle {
    pub async fn next(&mut self) -> Option<StreamEvent> { self.rx.recv().await }
    pub fn cancel(&self) { self.cancel.cancel(); }
    pub async fn collect(mut self) -> Result<CompletionResponse, ProviderError> { ... }
}
```

### 實作

| Provider | 檔案 | API | 涵蓋範圍 |
|----------|------|-----|----------|
| `AnthropicProvider` | `anthropic.rs` | `POST /v1/messages` SSE streaming | Claude 全系列 |
| `OpenAiCompatProvider` | `openai.rs` | `POST /v1/chat/completions` SSE | OpenAI、Ollama、LiteLLM、vLLM、Groq、Together 等 |
| `RetryProvider<P>` | `retry.rs` | Decorator pattern | 指數退避 + jitter，只重試 `is_retryable()` |
| `MockProvider` | `mock.rs`（test-kit） | — | 測試用，零 API key |
| `RecordedProvider` | `recorded.rs`（test-kit） | — | 回放 fixture 檔案 |

SSE 解析用 `eventsource-stream` crate（輕量、專注 SSE）。

### ProviderError

```rust
#[derive(Debug, thiserror::Error)]
pub enum ProviderError {
    #[error("API error ({status}): {message}")]
    Api { status: u16, error_type: String, message: String },
    #[error("Rate limited by {provider} (retry after {retry_after_secs}s)")]
    RateLimited { provider: String, retry_after_secs: u64 },
    #[error("Context overflow: {used} tokens > {limit} limit")]
    ContextOverflow { used: u32, limit: u32 },
    #[error("Authentication failed for {provider}")]
    AuthFailed { provider: String },
    #[error("Model '{model}' not found")]
    ModelNotFound { model: String },
    #[error("Network error: {0}")]
    Network(String),
    #[error("Cancelled")]
    Cancelled,
    #[error("Timeout after {secs}s")]
    Timeout { secs: u64 },
}

impl ProviderError {
    pub fn is_retryable(&self) -> bool {
        matches!(self, Self::RateLimited { .. } | Self::Network(_) | Self::Timeout { .. })
    }
}
```

---

## Sub-Agent 架構（Phase 1 MVP）

### 核心抽象

```rust
// === agent/types.rs ===
pub struct AgentDefinition {
    pub name: String,
    pub model: String,
    pub max_turns: u32,            // 預設 10
    pub timeout: Duration,         // 預設 300s
    pub tool_whitelist: Option<HashSet<String>>,
    pub system_prompt: Option<String>,
}

// === agent/runner.rs ===
#[async_trait]
pub trait AgentRunner: Send + Sync {
    async fn run(&self, request: AgentRequest, cancel: CancellationToken) -> AgentResult;
}

// === agent/handle.rs ===
pub struct AgentHandle {
    pub agent_id: AgentId,
    pub name: String,
    result_rx: oneshot::Receiver<AgentResult>,
    cancel: CancellationToken,
}

// === agent/spawner.rs ===
pub struct AgentSpawner {
    runner: Arc<dyn AgentRunner>,
    tracker: TaskTracker,
    current_depth: u32,              // 0 = root, 1 = sub-agent, ...
    max_depth: u32,                  // 預設 2（允許 parent → child → grandchild）
    parent_cancel: CancellationToken,
}
```

### Channel 架構（分階段）

```
Phase 1（MVP）：oneshot
    Parent → spawn(A) → tokio::spawn → [Sub-agent A] ──oneshot──→ AgentResult
    CancellationToken 樹：parent → child_A, child_B, child_C

Phase 2（Team）：+ mpsc mailbox（新增，不改現有）
    AgentHandle 加 inbox_tx: Option<mpsc::Sender<AgentMessage>>
    加 TaskRegistry: Arc<RwLock<Vec<Task>>>
    加 spawn_teammate()

Phase 3（跨程序）：+ Redis Streams（新增，不改現有）
    AgentMessage 序列化為 JSON，透過 Redis 傳遞
```

### Context 隔離

| 共享 | 隔離 |
|------|------|
| SMITHY.md 內容（String 傳遞） | 對話歷史（各自獨立） |
| Provider 連線（Arc 共享） | Token 預算（各自 max_turns + timeout） |
| Tool 集合（可用 whitelist 過濾） | |
| 檔案系統（共享讀寫） | |

---

## Agent Loop 設計

```rust
// smithy-agent/src/llm_runner.rs

loop {
    // === 停止條件 ===
    if cancel.is_cancelled()          → Cancelled
    if elapsed > timeout              → TimedOut
    if turns >= max_turns (預設 100)  → MaxTurns
    if consecutive_errors >= 3        → Failed

    // === Context 壓縮 ===
    if context.utilization() > 0.85   → micro_compact()  // 留 15% buffer + 2000 tok cushion

    // === 串流 LLM 呼叫 ===
    let mut handle = provider.stream(request).await?;
    loop {
        tokio::select! {
            event = handle.next() => match event {
                Some(TextDelta(d))     => { print!("{d}"); text.push_str(&d); }
                Some(ToolUseEnd { .. })=> { tool_calls.push(...); }
                Some(Done { .. })      => break,
                None                   => break,
                _ => {}
            },
            _ = cancel.cancelled() => return Cancelled,
        }
    }

    // === 無 tool calls = 自然完成 ===
    if tool_calls.is_empty() → Completed

    // === 執行 tool calls ===
    for tc in &tool_calls {
        hooks.dispatch(PreToolUse, &tc)?     // 可 block/modify
        permissions.check(&tc)?              // 可 deny
        let result = tools.execute(&tc)
        hooks.dispatch(PostToolUse, &tc, &result)
    }
}
```

### Ctrl-C 兩階段語義

```
第一次 Ctrl-C → 取消當前 tool call（CancellationToken 只取消工具執行）
第二次 Ctrl-C（2 秒內）→ 停止整個 agent session
```

### Crash Recovery（Phase 0 即加入）

每個 turn 結束後 append 到 `~/.local/share/smithy/sessions/{id}.jsonl`。crash 後可用 `smithy --resume` 恢復。不等 Phase 2 的完整 session 管理。

---

## 可插拔 Edit Format（蠶食 Aider）

```rust
pub enum EditFormat {
    SearchReplace,   // 預設，Claude/GPT-4o 最佳
    UnifiedDiff,     // GPT-4 Turbo 最省 token
    WholeFile,       // GPT-3.5/小模型，穩定但 token 成本高
}

// 設定
// smithy.toml: edit_format = "search-replace" | "unified-diff" | "whole-file"
// 或由 Provider 自動選擇最佳格式
```

---

## .smithyignore（Phase 0 即加入）

```gitignore
# 預設規則（內建，不需使用者設定）
.git/
node_modules/
target/
.env
*.key
*.pem

# 使用者自訂（.smithyignore 檔案）
vendor/
build/
```

Read/Write/Edit/Glob/Grep 全部尊重 `.smithyignore`，agent 不會讀寫被忽略的檔案。

---

## 檔案 Advisory Locking（Sub-agent 並行安全）

```rust
// smithy-executor/src/file_lock.rs
pub struct FileLockGuard {
    path: PathBuf,
    _lock: fd_lock::RwLock<File>,
}

impl FileLockGuard {
    pub fn write_lock(path: &Path) -> Result<Self, LockError>;
    pub fn read_lock(path: &Path) -> Result<Self, LockError>;
}
```

Write/Edit 工具執行前自動獲取 write lock，Read 工具獲取 read lock。多個 sub-agent 並行讀取不阻塞，寫入互斥。

---

## Auto-Lint 閉環（蠶食 Aider，Phase 1）

```toml
# .smithy/config.toml
[lint]
enabled = true
command = "cargo clippy --message-format=json"  # 或 "ruff check" / "biome check src/"
auto_fix = false   # true = 自動修復 + 重試

[test]
enabled = false
command = "cargo test"
on_edit = true     # Edit 後自動跑 test
```

流程：Edit → PostToolUse hook 觸發 lint → lint 輸出注入下一輪 context → agent 自動修正 → 再 lint → 閉環（最多 3 次）。

---

## 輕量 Repo-Map（Phase 1，蠶食 Aider）

Session 開始時，用 tree-sitter 提取所有檔案的 top-level symbols（class/fn/struct/trait），生成 ~2000 token 的 codebase 摘要注入 system prompt。

```rust
// smithy-tools/src/repo_map.rs
pub struct RepoMap {
    symbols: Vec<FileSymbols>,  // 每個檔案的 top-level symbols
}

impl RepoMap {
    /// 掃描工作目錄，提取符號（尊重 .smithyignore）
    pub fn scan(root: &Path, ignore: &IgnoreRules) -> Self;

    /// 生成適合注入 system prompt 的文字摘要
    pub fn to_prompt(&self, max_tokens: usize) -> String;
}
```

Phase 1 只做 extraction，不做 Aider 的 ranking（Phase 3 再加）。

---

## Prompt Caching + Token 用量儀表板

### Prompt Caching（Anthropic cache_control）

```rust
pub struct CompletionRequest {
    // ...existing fields...
    pub cache_control: Option<CacheControl>,  // system + tools 快取
}

pub enum CacheControl {
    Ephemeral,      // 5 分鐘快取
    Persistent,     // 持久快取
}
```

長 session 可減少 40-90% input tokens。

### Token 用量追蹤

```bash
smithy usage                    # 顯示今日/本週/本月用量
smithy usage --session abc123   # 特定 session 用量
```

```rust
// smithy-agent/src/usage.rs
pub struct UsageTracker {
    session_usage: HashMap<SessionId, CumulativeUsage>,
    daily_budget: Option<f64>,  // 每日預算（USD），超過警告
}
```

### Cost Budget（Goose 有此功能）

```toml
[budget]
daily_limit_usd = 5.0     # 每日上限
warn_at_percent = 80       # 80% 時警告
```

---

## MCP 補充：Sampling + Resources + Prompts

```rust
impl McpManager {
    // ...existing methods...

    /// MCP Sampling：server 反向請求 host LLM 推理
    pub async fn handle_sampling_request(
        &self,
        request: SamplingRequest,
        provider: &dyn Provider,
    ) -> Result<SamplingResponse, McpError>;

    /// 列出 MCP Resources
    pub fn list_resources(&self) -> Vec<ResourceDefinition>;

    /// 讀取 MCP Resource
    pub async fn read_resource(&self, uri: &str) -> Result<ResourceContent, McpError>;

    /// 列出 MCP Prompts
    pub fn list_prompts(&self) -> Vec<PromptDefinition>;

    /// 取得 MCP Prompt
    pub async fn get_prompt(&self, name: &str, args: Value) -> Result<Vec<Message>, McpError>;
}
```

沒有 sampling handler，2025-2026 新 MCP server（如 claude-memory、browser-use）無法正常運作。

---

## Model 格式統一

```
provider::model 格式，消除歧義：
  "anthropic::claude-sonnet-4-20250514"
  "openai::gpt-4o"
  "ollama::llama3.1"
  "groq::llama-3.1-70b-versatile"

省略 provider 前綴 = 使用預設 provider：
  "claude-sonnet-4-20250514" → 走 [providers.default] 設定
```

---

## API Key 安全

- log output 自動 mask：`sk-ant-api03-...` → `sk-ant-***`
- error message 不含完整 key
- `--debug` 模式也不例外
- `smithy-types` 提供 `mask_sensitive(s: &str) -> String` 工具函式

---

## Atomic Multi-File Edit（Rollback 支援）

```rust
pub struct EditTransaction {
    edits: Vec<PendingEdit>,
    backups: Vec<(PathBuf, Vec<u8>)>,  // 原始內容備份
}

impl EditTransaction {
    pub fn add(&mut self, path: &Path, old: &str, new: &str);
    pub fn commit(&mut self) -> Result<(), EditError>;   // 全部套用
    pub fn rollback(&self) -> Result<(), EditError>;     // 全部回滾
}
```

多檔案修改全成功或全回滾（Aider 和 CC 都有此保證）。

---

## Hook 系統補充：獨立 Budget

```rust
pub struct HookDispatcher {
    // ...
    critical_budget_ms: u64,    // critical hooks 獨立 budget（預設 10000）
    deferrable_budget_ms: u64,  // deferrable hooks 獨立 budget（預設 5000）
}
```

Critical 和 deferrable hooks 各有獨立計時，避免 critical 吃完所有時間導致 deferrable audit hooks 被跳過。

新增 2 個遺漏事件：
```rust
    ModelResponse,       // LLM response 回來後、tool 執行前
    ToolUseStart,        // tool 開始執行（區別 PreToolUse 的 before-dispatch）
```

---

## Skill 系統

相容 Claude Code `.md` + YAML frontmatter 格式，但自足載入：

```rust
pub struct SkillMetadata {
    pub name: String,
    pub description: String,      // ~100 tokens（常駐 system prompt）
    pub version: Option<String>,
    pub tools: Vec<String>,
    pub disable_auto: bool,
    pub file_path: PathBuf,       // content 惰性讀取
}

// 載入路徑：
// 1. 內建 skills/ 目錄
// 2. ~/.config/smithy/skills/
// 3. .smithy/skills/（專案層級）
```

## 完整 Tool 清單（蠶食 6 大 CLI agent 交叉比對）

### 採用矩陣

```
                  CC   OH  Aider Goose Cline Codex  Smithy
Read              ✓    ✓    ✓     ✓     ✓     ✓     Phase 0 ★
Write             ✓    ✓    ✓     ✓     ✓     ✓     Phase 0 ★
Edit              ✓    ✓    ✓     ✓     ✓     ✓     Phase 0 ★
Bash              ✓    ✓    ✓     ✓     ✓     ✓     Phase 0 ★
Glob              ✓    ✓    ✗     ✗     ✓     ✗     Phase 0 ★
Grep              ✓    ✓    ✗     ✗     ✓     ✗     Phase 0 ★
Agent             ✓    ✓    ✗     ✗     ✗     ✗     Phase 1 ★
MCP               ✓    ✓    ✗     ✓     ✓     ✓     Phase 1 ★
WebSearch         ✓    ✓    ✗     ✗     ✗     ✓     Phase 1
WebFetch          ✓    ✓    ✓     ✗     ✗     ✗     Phase 1
NotebookEdit      ✓    ✓    ✗     ✗     ✗     ✗     Phase 2
Task Mgmt         ✓    ✓    ✗     ✗     ✗     ✗     Phase 2
Plan Mode         ✓    ✓    ✗     ✗     ✗     ✗     Phase 2
AskUser           ✓    ✓    ✗     ✗     ✗     ✗     Phase 1
```

### Phase 0 Tools（6 個，核心）

| Tool | 說明 | 蠶食來源 |
|------|------|----------|
| `Read` | 讀取檔案內容（offset/limit 分頁、圖片辨識、PDF） | CC 的完整實作 |
| `Write` | 建立/覆寫檔案 | CC |
| `Edit` | search-replace 精確替換 | CC + Aider 可插拔 edit format |
| `Bash` | Shell 指令執行（timeout、output capture、sandbox） | CC + Goose 防爆 |
| `Glob` | 快速檔案模式搜尋（globwalk） | CC |
| `Grep` | 內容搜尋（ripgrep 封裝，支援 regex、context lines） | CC |

### Phase 1 Tools（+6 個，差異化）

| Tool | 說明 | 蠶食來源 |
|------|------|----------|
| `Agent` | Sub-agent 生成（AgentSpawner 整合） | CC agent tool |
| `McpTool` | 動態 MCP 工具路由（namespace::tool_name） | Goose MCP-first |
| `WebSearch` | 可插拔搜尋（預設 Brave Search 免費 tier，`SearchBackend` trait 可換 SearXNG/Bing） | CC + Codex |
| `WebFetch` | 取得網頁內容（reqwest + HTML→text 轉換） | CC |
| `AskUser` | 向使用者提問並等待回答 | CC |
| `GitOps` | gix 操作（status、diff、commit），opt-in auto-commit | Aider git-first |

### Phase 2 Tools（+4 個，生產級）

| Tool | 說明 |
|------|------|
| `NotebookEdit` | Jupyter notebook cell 編輯 |
| `TaskCreate/Get/List/Update` | 結構化任務管理（Team agent 基礎） |
| `PlanMode` | Enter/Exit plan mode（唯讀探索 + 計畫撰寫） |
| `Worktree` | Git worktree 隔離（Enter/Exit） |

---

## MCP 整合（smithy-mcp crate）

### 架構

```rust
// smithy-mcp/src/lib.rs

pub struct McpManager {
    servers: HashMap<String, McpServerHandle>,
    tool_registry: HashMap<String, McpToolMeta>,  // "server::tool_name"
}

pub struct McpServerConfig {
    pub name: String,
    pub command: String,
    pub args: Vec<String>,
    pub env: HashMap<String, String>,
    pub timeout_secs: u64,
}

impl McpManager {
    /// 啟動所有設定的 MCP servers，執行 handshake，快取 tool lists
    pub async fn initialize(configs: &[McpServerConfig]) -> Result<Self, McpError>;

    /// 列出所有 MCP tools（含命名空間）
    pub fn list_tools(&self) -> Vec<ToolDefinition>;

    /// 路由 tool call 到正確的 server
    pub async fn call_tool(&self, namespaced_name: &str, args: Value) -> Result<ToolOutput, McpError>;

    /// 優雅關閉所有 servers
    pub async fn shutdown(&mut self);
}
```

### 命名空間

- 內建工具：無前綴（`Read`、`Write`、`Bash`）
- MCP 工具：`{server_name}::{tool_name}`（如 `github::create_issue`）
- 衝突策略：內建 > 使用者定義 > MCP

### 傳輸支援

| 傳輸 | Phase | 依賴 |
|------|-------|------|
| stdio（子程序） | Phase 1 | rmcp 內建 |
| Streamable HTTP | Phase 2 | reqwest + SSE |

### 設定格式

```toml
[[mcp_servers]]
name = "github"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_TOKEN = "${GITHUB_TOKEN}" }
timeout_secs = 30

[[mcp_servers]]
name = "filesystem"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
```

### 錯誤處理

- Server 崩潰 → tool 回傳 `is_error: true`，agent loop 繼續
- Phase 2 加入 `ResilientMcpClient`：指數退避重連 + 健康檢查
- `tools/list_changed` 通知 → 動態刷新 tool registry

### 關鍵依賴

```toml
rmcp = "0.16"  # 官方 MCP Rust SDK
```

---

## Hook 系統（完整復刻 Claude Code，21 個事件）

### 所有 Hook Events

```rust
pub enum HookEvent {
    // === Session 生命週期 ===
    SessionStart,
    SessionEnd,

    // === 主迴圈 ===
    UserPromptSubmit,        // 使用者送出 prompt 前（可修改 prompt）
    PreToolUse,              // 工具執行前（可 block / modify input）
    PostToolUse,             // 工具執行後（可記錄 / 觸發副作用）
    PostToolUseFailure,      // 工具執行失敗後
    PermissionRequest,       // 權限請求時
    Stop,                    // Agent 停止時
    Notification,            // 通知事件

    // === Sub-agent ===
    SubagentStart,
    SubagentStop,

    // === Context ===
    PreCompact,              // 壓縮前
    PostCompact,             // 壓縮後

    // === Config/File ===
    ConfigChange,            // 設定變更
    ConfigLoad,              // 設定載入
    InstructionsLoaded,      // SMITHY.md 載入
    FileChanged,             // 檔案變更偵測
    CwdChanged,              // 工作目錄變更

    // === Task（Phase 2） ===
    TaskCreated,
    TaskCompleted,

    // === Worktree（Phase 2） ===
    WorktreeCreate,
    WorktreeRemove,
}
```

### 設定格式（相容 Claude Code settings.json 結構）

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "./hooks/safety-check.sh",
            "timeout": 5000
          }
        ]
      },
      {
        "matcher": "mcp__*",
        "hooks": [
          {
            "type": "command",
            "command": "./hooks/mcp-audit.sh",
            "timeout": 3000
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "./hooks/prompt-filter.sh"
          }
        ]
      }
    ]
  }
}
```

### Subprocess 執行協議

**stdin JSON**：
```json
{
  "hook_event": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": { "command": "rm -rf /tmp/test" },
  "session_id": "abc123",
  "agent_id": "def456"
}
```

**stdout JSON**：
```json
{
  "decision": "block",
  "reason": "Dangerous rm -rf command blocked",
  "updatedInput": null
}
```

**或修改 input**：
```json
{
  "decision": "allow",
  "updatedInput": {
    "command": "rm -rf /tmp/test --dry-run"
  }
}
```

**Exit codes**：
- `0` = 成功，解析 stdout JSON 決策
- `2` = 阻擋，stderr 作為阻擋原因
- 其他 = 忽略（hook 執行失敗不阻擋工具）

### Matcher 語法

- `"Bash"` — 精確比對
- `"Edit|Write"` — OR（pipe 分隔）
- `"mcp__github__*"` — glob pattern
- `"*"` — 所有工具

### 兩階段執行

```rust
pub struct HookDispatcher {
    hooks: HashMap<HookEvent, Vec<HookEntry>>,
    critical_handlers: HashSet<String>,  // 永遠執行
    blocking_budget_ms: u64,             // 預設 5000
}

impl HookDispatcher {
    pub async fn dispatch(&self, event: HookEvent, payload: &HookPayload) -> HookAction {
        let mut final_action = HookAction::Allow;

        // Phase 1: Critical hooks — 永遠執行
        for hook in self.get_critical(event) {
            let action = self.execute_hook(hook, payload).await;
            final_action = merge(final_action, action);  // block > allow
        }

        // Phase 2: Deferrable hooks — 在 budget 內執行
        let start = Instant::now();
        for hook in self.get_deferrable(event) {
            if start.elapsed().as_millis() > self.blocking_budget_ms { break; }
            let action = self.execute_hook(hook, payload).await;
            final_action = merge(final_action, action);
        }

        final_action
    }
}
```

### 已知 Claude Code Bug（Smithy 需規避）

| Bug | Smithy 解決方案 |
|-----|----------------|
| 子程序繼承 `CLAUDECODE=1` 導致 SDK 失效 | 不設環境旗標，或用 `SMITHY_HOOK=1` 且文件明確 |
| Windows subprocess 死鎖 | 使用 tokio::process + timeout 強制清理 |
| ~2.5h 後 hooks 停止執行 | 每 hook 獨立 subprocess spawn，不重用 |

---

## 多 LLM Provider 設計（3 大 API 差異處理）

### API 差異矩陣

| 維度 | Anthropic | OpenAI(-compatible) | Gemini |
|------|-----------|---------------------|--------|
| System prompt | 頂層 `system` 欄位 | `role: "system"` 訊息 | `systemInstruction` 欄位 |
| Tool 定義 | `{name, description, input_schema}` | `{type:"function", function:{name, parameters}}` | `{functionDeclarations:[{name, parameters}]}` |
| Tool call 回應 | content block `{type:"tool_use", id, name, input}` | `tool_calls:[{id, function:{name, arguments:"JSON_STRING"}}]` | `functionCall:{name, args}` |
| Tool result | `{type:"tool_result", tool_use_id, content}` | `{role:"tool", tool_call_id, content}` | `functionResponse:{name, response}` |
| Streaming | 命名 SSE 事件（message_start, content_block_delta...） | Delta chunks + `[DONE]` | 完整 response 每 chunk |
| Token 用量 | `usage.{input_tokens, output_tokens}` | `usage.{prompt_tokens, completion_tokens}` | `usageMetadata.{promptTokenCount, candidatesTokenCount}` |
| 特殊功能 | Extended thinking, prompt caching | Structured output, parallel tool calls | Code execution, grounding |

### 統一轉換層

```rust
// smithy-provider/src/convert.rs

/// 內部正規化訊息格式（Anthropic 風格 content blocks）
pub struct NormalizedMessage {
    pub role: Role,
    pub content: Vec<ContentBlock>,
}

pub enum ContentBlock {
    Text(String),
    Image { source: ImageSource, media_type: String },  // multimodal 支援
    ToolUse { id: String, name: String, input: Value },
    ToolResult { tool_use_id: String, content: String, is_error: bool },
    Thinking { text: String, budget_tokens: Option<u32> },  // extended thinking
}

/// 每個 Provider 實作這些轉換
trait ProviderAdapter {
    fn build_request(&self, messages: &[NormalizedMessage], tools: &[ToolDef], system: &str) -> Value;
    fn parse_response(&self, body: &Value) -> Vec<NormalizedMessage>;
    fn parse_stream_chunk(&self, chunk: &str) -> Vec<StreamEvent>;
    fn extract_usage(&self, body: &Value) -> TokenUsage;
}
```

### Provider 清單

| Provider | 實作 | Phase | 覆蓋 |
|----------|------|-------|------|
| Anthropic | `AnthropicProvider` | Phase 0 | Claude 全系列 |
| OpenAI-compatible | `OpenAiProvider` | Phase 1 | OpenAI, Ollama, LiteLLM, Groq, Deepseek, Together, Fireworks, vLLM |
| Gemini | `GeminiProvider` | Phase 2 | Gemini 1.5/2.0 |

**OpenAI-compatible 一套涵蓋**：只需換 `base_url` + `api_key`，同一份代碼跑所有 OpenAI-compatible API。

### 設定

```toml
[providers.anthropic]
api_key_env = "ANTHROPIC_API_KEY"
default_model = "claude-sonnet-4-20250514"

[providers.openai]
api_key_env = "OPENAI_API_KEY"
default_model = "gpt-4o"

[providers.ollama]
base_url = "http://localhost:11434/v1"
default_model = "llama3.1"
# 無需 api_key

[providers.groq]
api_key_env = "GROQ_API_KEY"
base_url = "https://api.groq.com/openai/v1"
default_model = "llama-3.1-70b-versatile"

[providers.gemini]
api_key_env = "GOOGLE_API_KEY"
default_model = "gemini-2.0-flash"
```

---

## Permission 模型

```rust
pub enum PermissionRule {
    Allow { tool: String, pattern: Option<String> },
    Deny { tool: String, pattern: Option<String> },
}
pub enum PermissionMode { Default, Auto, Plan }
```

---

## 設定系統

**格式**：TOML（Rust 生態標準）
**路徑**：XDG-compliant（`dirs` crate）
**優先級**：compiled defaults < `~/.config/smithy/config.toml` < `.smithy/config.toml` < env vars < CLI flags

```toml
[provider]
default = "anthropic"
model = "claude-sonnet-4-20250514"

[provider.api_keys]
# 優先用 env vars: ANTHROPIC_API_KEY, OPENAI_API_KEY

[provider.endpoints]
# ollama = "http://localhost:11434/v1"

[agent]
max_turns = 100
timeout_secs = 300

[permissions]
mode = "default"

[[permissions.deny]]
tool = "Bash"
pattern = "rm -rf*"
```

**SMITHY.md**：專案層級指令檔（類似 CLAUDE.md），純文字注入 system prompt。

---

## 分階段實作

### Phase 0（3 週）— 骨架：6 個核心工具 + 串流 CLI

| 項目 | Crate | 說明 |
|------|-------|------|
| Workspace scaffold | all | Cargo workspace、CI（clippy/fmt/test/doc）、README、CONTRIBUTING |
| 核心型別 | smithy-types | Message, ToolCall, ToolResult, Usage, ContentBlock, Error 階層 |
| 設定 | smithy-config | TOML 載入、XDG 路徑、env vars、SMITHY.md |
| Provider | smithy-provider | Provider trait + Anthropic SSE streaming（reqwest + eventsource-stream） |
| Executor | smithy-executor | Bash sandbox + file advisory locking + cwd isolation |
| **Tools（6 個）** | smithy-tools | Tool trait + **Read, Write, Edit, Bash, Glob, Grep** |
| **.smithyignore** | smithy-executor | 內建預設規則 + 使用者自訂，所有工具尊重 |
| Agent loop | smithy-agent | LlmAgentRunner + 5 停止條件 + **Ctrl-C 兩階段語義** |
| **Crash recovery** | smithy-agent | 每 turn append JSONL，crash 後 `--resume` 恢復 |
| CLI | smithy-cli | `smithy -p "prompt"` headless + 簡單 REPL |
| Test kit | smithy-test-kit | MockProvider, RecordedProvider, fixture 載入 |
| 安全 | smithy-types | API key masking（log/error 自動遮蔽） |

**驗證**：`smithy -p "Create hello.txt with Hello World"` 全流程串流輸出 + 工具使用 + `.smithyignore` 生效。

### Phase 1（4 週）— 差異化：sub-agent + MCP + hooks + multi-provider + 6 工具

| 項目 | Crate | 說明 |
|------|-------|------|
| **Tools（+6）** | smithy-tools | Agent, McpTool, WebSearch, WebFetch, AskUser, GitOps |
| Sub-agent | smithy-agent | AgentRunner/Spawner/Handle, CancellationToken 樹 |
| **MCP 客戶端** | smithy-mcp | rmcp stdio 傳輸、McpManager、命名空間路由、server lifecycle |
| Skills | smithy-skills | YAML frontmatter loader, keyword matcher, lazy content |
| **Hooks（23 事件）** | smithy-hooks | 完整 Claude Code hook 復刻 + ModelResponse/ToolUseStart、獨立 budget |
| Permissions | smithy-permissions | Allow/Deny glob matching, 三模式（default/auto/plan） |
| **OpenAI-compat** | smithy-provider | 一套涵蓋 OpenAI/Ollama/LiteLLM/Groq/Deepseek/Together |
| **Repo-map（輕量）** | smithy-tools | tree-sitter symbol extraction → ~2000 tok codebase 摘要 |
| **Auto-lint 閉環** | smithy-hooks | PostToolUse 觸發 lint → 結果注入 context → agent 自修正 |
| **Prompt caching** | smithy-provider | Anthropic cache_control 支援（減 40-90% input tokens） |
| **Cost budget** | smithy-agent | 每日預算上限（USD），80% 警告，100% 停止 |
| Testing | all | 每 crate unit tests + integration tests with MockProvider |

**驗證**：
- sub-agent 並行搜尋
- MCP server 連接 + tool 呼叫
- hook 阻擋危險 bash 指令 + tool input 修改
- Anthropic + OpenAI + Ollama 三路 provider 都能用

### Phase 2（4-5 週）— 生產級 + Gemini + TUI

| 項目 | Crate | 說明 |
|------|-------|------|
| **Tools（+4）** | smithy-tools | NotebookEdit, TaskCreate/Get/List/Update, PlanMode, Worktree |
| **Gemini Provider** | smithy-provider | GeminiProvider（獨立 API 格式） |
| MCP 完整 | smithy-mcp | Streamable HTTP + ResilientMcpClient + **Sampling handler + Resources + Prompts** |
| Context 三層壓縮 | smithy-agent | Micro（本地修剪）→ Auto（LLM 摘要）→ Full（重寫） |
| Session 持久化 | smithy-agent | JSONL save/resume |
| Interactive TUI | smithy-cli | ratatui-based interactive mode |
| Agent 定義檔 | smithy-config | `.smithy/agents/*.md` YAML frontmatter |
| Release pipeline | CI | cargo publish、GitHub releases、brew formula |
| 文件 | docs/ | mdBook user guide、architecture guide、adding-a-provider tutorial |

### Phase 3（持續）— 社群 + 進階

| 項目 | 說明 |
|------|------|
| Team agents | TaskRegistry + mpsc mailbox + spawn_teammate() |
| Repo map | tree-sitter 符號提取 + ranking（蠶食 Aider） |
| Plugin system | Script-based tools + WASM sandbox |
| Benchmarks | SWE-bench 子集自動測試 |
| 更多 Provider | AWS Bedrock, Azure OpenAI, Mistral, Cohere |
| **Server Mode** | `smithy serve --port 8080`（HTTP/WebSocket API，agent 邏輯零改動） |
| **Embeddable Runtime** | `smithy-agent` 作為 library crate 被第三方嵌入（IDE 擴展、web 服務、bot） |

---

## 戰略設計：Library-First Agent Runtime

### 為什麼這很重要

Smithy 不只是一個 CLI 工具——`smithy-agent` 是一個**可嵌入的 agent runtime**。CLI 只是眾多 I/O adapter 之一。這個設計讓 Smithy 的架構經驗直接遷移到 Agent SDK 場景。

```
                 smithy-agent（核心 runtime，純 library）
                 ╱          │          ╲
         smithy-cli    smithy-server   第三方嵌入
         (terminal)    (HTTP/WS API)   (IDE/bot/SaaS)
```

### 架構原則：Operator Composability

每個 crate 都是一個 **Operator**——接收輸入、產出輸出、可組合。找最大公因數（agent loop），然後像樂高一樣組合不同的 I/O adapter。

```
User Input ──→ [Provider] ──→ [Agent Loop] ──→ [Tool Router] ──→ [Executor]
                                   │
                              [Hooks]  [Permissions]  [Context Manager]
```

CLI 和 Server 的差異**只在 I/O 邊界**，不在 agent 邏輯：

| 層 | CLI Mode | Server Mode | SDK Mode |
|----|----------|-------------|----------|
| 輸入 | stdin / `-p "prompt"` | HTTP POST / WebSocket | 函式呼叫 |
| 輸出 | stdout streaming | SSE / WebSocket streaming | async Stream |
| Session | 本地 JSONL | Server-side DB | 呼叫方管理 |
| Auth | 本地 API key | Bearer token + multi-tenant | 嵌入方提供 |
| 工具確認 | stdin y/n | HTTP callback / auto | 嵌入方實作 PermissionChecker |

### smithy-agent 的 Public API（Library 使用）

```rust
// 第三方嵌入 smithy-agent 的最小範例

use smithy_agent::{AgentBuilder, AgentEvent};
use smithy_provider::AnthropicProvider;
use smithy_tools::default_tools;

#[tokio::main]
async fn main() {
    let provider = AnthropicProvider::from_env().unwrap();

    let agent = AgentBuilder::new()
        .provider(provider)
        .tools(default_tools())
        .working_dir("./my-project")
        .system_prompt("You are a helpful coding assistant.")
        .max_turns(50)
        .build();

    // 串流方式消費 agent 事件
    let mut stream = agent.run("Fix the bug in auth.rs").await.unwrap();

    while let Some(event) = stream.next().await {
        match event {
            AgentEvent::TextDelta(text) => print!("{text}"),
            AgentEvent::ToolStart { name, .. } => println!("[Using {name}]"),
            AgentEvent::ToolResult { .. } => {},
            AgentEvent::Complete { usage, .. } => {
                println!("\nDone! Tokens: {}", usage.total());
                break;
            }
            AgentEvent::Error(e) => {
                eprintln!("Error: {e}");
                break;
            }
        }
    }
}
```

### Server Mode（Phase 3）

```rust
// smithy-server/src/main.rs（獨立 binary crate，Phase 3）

use smithy_agent::AgentBuilder;
use axum::{Router, routing::post, extract::Json};

async fn run_agent(Json(req): Json<AgentRequest>) -> impl IntoResponse {
    let agent = AgentBuilder::new()
        .provider_from_config(&req.provider)
        .tools(default_tools())
        .working_dir(&req.working_dir)
        .build();

    // 回傳 SSE stream
    let stream = agent.run(&req.prompt).await?;
    Sse::new(stream.map(|event| Event::default().json_data(event)))
}

let app = Router::new()
    .route("/v1/agent/run", post(run_agent))
    .route("/v1/agent/resume", post(resume_agent))
    .route("/v1/sessions", get(list_sessions));
```

### 與 Agent SDK 的對應關係

| Smithy 概念 | Anthropic Agent SDK 對應 | 學到什麼 |
|-------------|------------------------|----------|
| `AgentRunner` trait | `Agent` class | agent 抽象的最小介面 |
| `Provider` trait + streaming | `client.messages.stream()` | 為什麼 SDK 的 streaming 長這樣 |
| `Tool` trait + ToolRegistry | `@tool` decorator + tool list | schema 設計、error 回報、input validation |
| `AgentSpawner` + depth control | `agent.spawn_subagent()` | 為什麼要限制 depth、隔離 context |
| `HookDispatcher` | SDK middleware / interceptors | lifecycle 事件在哪裡插入最有價值 |
| `PermissionChecker` | Human-in-the-loop approval | 為什麼權限不能全是 allow/deny |
| `ContextManager` + compression | Context window management | 為什麼 SDK 要暴露 token counting API |
| `McpManager` | MCP server integration | 為什麼 MCP 的 tool namespace 很重要 |
| `CancellationToken` tree | Cancellation / timeout | 為什麼 SDK 要支援 mid-stream abort |
| `EditTransaction` rollback | Atomic operations | 為什麼 SDK 要有 undo/checkpoint |

### 不重疊的領域（SDK 特有，Smithy 不碰）

| Agent SDK 獨有 | 為什麼 Smithy 不碰 | 什麼時候碰 |
|---------------|-------------------|-----------|
| Multi-tenant isolation | CLI 是單用戶 | Server Mode 時自然需要 |
| Serverless cold start | CLI 是長駐程序 | Server Mode 時考慮 |
| Billing/metering per user | CLI 是自己的 key | Server Mode + SaaS 時 |
| OAuth / API key management UI | CLI 用 env var | Server Mode dashboard |
| Webhook / callback endpoints | CLI 是主動方 | Server Mode 時自然有 |
| Deployment orchestration | 本地執行 | 未來 cloud offering |

**結論**：Smithy CLI → Server Mode → Embeddable Library 是一條自然的演化路徑。70% 的 agent 核心邏輯（loop、tools、hooks、provider、context）完全共用，只有 I/O 邊界層需要適配。打磨 CLI 就是在打磨未來的 SDK runtime。

### Crate 可見性設計

為了支援 library 嵌入，crate 的 public API 需要刻意設計：

| Crate | 對外 API | 對 CLI 的 API |
|-------|---------|--------------|
| `smithy-types` | 所有型別 public | — |
| `smithy-provider` | `Provider` trait + 3 impl + `ProviderBuilder` | — |
| `smithy-tools` | `Tool` trait + `ToolRegistry` + `default_tools()` | — |
| `smithy-agent` | `AgentBuilder` + `AgentEvent` stream + `AgentResult` | — |
| `smithy-hooks` | `HookDispatcher` + `HookEvent` + `HookAction` | — |
| `smithy-mcp` | `McpManager` + `McpServerConfig` | — |
| `smithy-skills` | `SkillRegistry` + `SkillMetadata` | — |
| `smithy-config` | `ForgeConfig::load()` | `CliOverrides` |
| `smithy-cli` | ❌ 不對外（binary crate） | 所有 |

**原則**：`smithy-cli` 是唯一不可嵌入的 crate。其他所有 crate 都可被第三方 `use smithy_agent::*` 直接使用。

---

## 開源品質標準

### Error 策略
- Library crates：`thiserror`（結構化、可 match）
- CLI boundary：`miette`（使用者友善診斷）
- 每個 Error variant 必須回答「什麼失敗了」和「為什麼」

### Testing
- `cargo test` **必須零外部依賴**（無 API key、無網路）
- MockProvider + RecordedProvider（fixture 回放）
- Property-based tests：序列化 roundtrip、config merge 結合律
- Integration tests 三平台 CI（Linux/macOS/Windows）

### CI
- `cargo fmt --check` + `cargo clippy -- -D warnings` + `cargo test` + `cargo doc`
- `cargo deny check`（授權 + 安全審計）
- Conventional commits + `git-cliff` 自動 changelog
- MSRV 固定在 `rust-toolchain.toml`

### 安裝方式
- `cargo install smithy-cli`
- `brew install org/tap/smithy`
- GitHub Releases（6 平台預建二進位）
- `curl -fsSL .../install.sh | sh`

---

## Repository 結構

```
smithy/
├── .github/workflows/
│   ├── ci.yml                 # lint + test + clippy on PR
│   └── release.yml            # tag-triggered builds + crates.io
├── crates/
│   ├── smithy-types/          # 所有共享型別 + Error
│   ├── smithy-config/         # TOML + XDG + SMITHY.md
│   ├── smithy-permissions/    # Allow/Deny + glob
│   ├── smithy-hooks/          # 兩階段 dispatcher
│   ├── smithy-provider/       # Provider trait + Anthropic + OpenAI
│   ├── smithy-executor/        # Bash sandbox + file locking + SSRF 防護
│   ├── smithy-tools/          # Tool trait + 12→16 內建工具
│   ├── smithy-mcp/            # MCP client (rmcp)
│   ├── smithy-skills/         # Skill loader
│   ├── smithy-agent/          # Agent loop + sub-agent
│   ├── smithy-cli/            # Binary crate
│   └── smithy-test-kit/       # Mock + fixture（dev-dep）
├── docs/book/                 # mdBook user guide
├── docs/adr/                  # Architecture Decision Records
├── examples/                  # custom_provider.rs, custom_tool.rs
├── fixtures/                  # 錄製的 API responses
├── skills/                    # 內建 skill .md 檔案
├── Cargo.toml                 # Workspace root
├── LICENSE-MIT
├── LICENSE-APACHE
├── README.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md               # 安全漏洞回報流程
├── SMITHY.md.example
├── .smithyignore.default     # 內建預設忽略規則
├── rust-toolchain.toml
├── rustfmt.toml
├── clippy.toml
└── deny.toml
```

---

## YAGNI 清單

| 不做（目前） | 原因 |
|-------------|------|
| Rig/rig-core 依賴 | 搶 agent loop 控制權，Tool trait 不匹配 |
| Tree-sitter **ranking**（Phase 0-1） | Aider 的 ranking 演算法複雜，Phase 1 只做 extraction，Phase 3 做 ranking |
| TUI（Phase 0-1） | CLI 先行，TUI 是 Phase 2（optional feature flag `--features tui`） |
| Team agent（Phase 0-1） | Sub-agent 先做好，Team 是 Phase 2 |
| Plugin dynamic loading | Skill + hook 就是輕量 plugin |
| Ractor/Kameo 監督樹 | Sub-agent 失敗返回 Failed 即可 |
| Agent 定義檔（Phase 0） | 硬編碼 3 種（explorer/worker/reviewer），Phase 2 才做 .md 載入 |
| Auto-commit 預設開啟 | 多數人有 dirty working tree，opt-in |
| Gemini Provider（Phase 0-1） | 獨立 API 格式，Phase 2 再做 |

---

## 關鍵依賴

```toml
[workspace.dependencies]
tokio = { version = "1", features = ["full"] }
tokio-util = { version = "0.7", features = ["rt"] }
reqwest = { version = "0.12", features = ["stream", "json", "rustls-tls"] }
eventsource-stream = "0.2"     # SSE 解析
serde = { version = "1", features = ["derive"] }
serde_json = "1"
serde_yaml = "0.9"
async-trait = "0.1"
thiserror = "2"
uuid = { version = "1", features = ["v7"] }
clap = { version = "4", features = ["derive"] }
toml = "0.8"
dirs = "5"                     # XDG 路徑（6.x 不存在）
gray_matter = "0.2"            # YAML frontmatter
globwalk = "0.9"
gix = { version = "0.68", default-features = false, features = ["basic", "status"] }
rmcp = { version = "=0.16.0", features = ["client", "transport-child-process"] }  # 釘住版本
tracing = "0.1"
tracing-subscriber = "0.3"
futures = "0.3"
miette = { version = "7", features = ["fancy"] }  # CLI 使用者友善錯誤

[profile.release]
opt-level = 3
lto = true
strip = true
codegen-units = 1
```

---

## 驗證計畫

### Phase 0
```bash
smithy -p "什麼是 Rust 的 ownership?"          # 串流對話
smithy -p "讀取 /tmp/test.txt"                 # 工具使用
smithy -p "建立 /tmp/hello.rs 含 Hello World"  # 寫檔
smithy -p "反覆讀取不存在的檔案"                 # 3 次錯誤後停止
cargo test                                      # 全 pass，零 API key
```

### Phase 1
```bash
smithy -p "用 sub-agent 並行搜尋 src/ 和 tests/ 的 TODO"
smithy -p "/commit"                             # skill 觸發
OPENAI_API_KEY=... smithy --provider openai -p "hello"  # 多 provider
cargo test --all                                # 含 integration tests
```

### Phase 2
```bash
smithy --resume                                 # session 恢復
smithy -p "透過 MCP 查詢外部工具"                # MCP 整合
cargo install smithy-cli                        # 從 crates.io 安裝
```
