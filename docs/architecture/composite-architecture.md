---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

# 複合架構 (Composite Architecture)

> SDK → CLI → MCP → Skill 四層複合架構，統一所有服務的存取介面。

---

## 設計理念

Workshop 的每個服務（Core Module 或 Station）都應具備多層存取介面，讓不同的使用者和工具能以最適合的方式操作：

| 層 | 使用者 | 特性 |
|----|--------|------|
| **SDK** | Python 程式碼、其他 CLI、MCP | 型別安全、可組合、程式化存取 |
| **CLI** | 人類終端、Shell 腳本、CI/CD | 互動式、管道友善、自文檔化 |
| **MCP** | Claude Code、AI Agent | 工具定義、參數映射、stdio 通訊 |
| **Skill** | Claude Code（LLM 層） | 自然語言觸發、工作流指引、最佳實踐 |

```
Human Terminal ──► CLI ──► SDK ──► Service API
Claude Code ────► MCP ──► SDK ──► Service API
                  Skill ──► CLI + MCP（參照，不匯入 SDK）
Python Script ──► SDK ──► Service API
```

**核心原則**：SDK 是基底，所有上層（CLI、MCP、Skill）都建構在 SDK 之上。Skill 只參照 CLI + MCP，永不直接匯入 SDK。

---

## 架構模式

### 四層路徑慣例

```
libs/sdk-client/sdk_client/{name}.py    ← SDK（繼承 BaseClient 或獨立）
stations/{name}/cli/{cmd}.py                   ← Station CLI（合併在 station 內）
core/cli/{name}.py                             ← Core Module CLI
mcp/{name}/server.py                           ← MCP（不變）
~/.claude/skills/{name}/SKILL.md               ← Skill（不變）
```

### SDK 四種變體

| 模式 | 適用 | 基底 | 範例 |
|------|------|------|------|
| **BaseClient HTTP** | Core Module（DB-backed） | 繼承 `BaseClient`，包裝 `/api/{module}/` | `FinanceClient` |
| **Standalone HTTP** | Station（獨立端口） | 獨立客戶端，包裝 `http://localhost:{port}` | `SentinelClient` |
| **Direct impl** | 本地工具（無 HTTP） | 直接實作邏輯 | `EnvkitClient` |
| **Subprocess** | CLI 優先工具 | 包裝現有 CLI 呼叫 | `EnvkitClient` (subprocess) |

### BaseClient 範例

```python
# Core Module SDK — 繼承 BaseClient
class FinanceClient(BaseClient):
    def __init__(self, **kwargs):
        super().__init__(module="finance", **kwargs)

    async def list_transactions(self, wallet_id=None, limit=20):
        params = {"limit": limit}
        if wallet_id:
            params["wallet_id"] = wallet_id
        return await self._get("/transactions", params=params)
```

```python
# Station SDK — 獨立客戶端
class SentinelClient:
    def __init__(self, base_url=None):
        self.base_url = base_url or os.environ.get(
            "SENTINEL_URL", "http://localhost:4101"
        )
```

### MCP 層設計（AD-2）

MCP Server 是 **SDK 的協定適配器**，不是 HTTP 的薄殼：

```
Claude Code ──► MCP Server ──► SDK Client ──► FastAPI Core ──► Database
                (tool def)     (typed API)     (business)       (persistence)
```

- MCP Server **禁止**直接存取 DB 或使用原始 `httpx` 呼叫
- MCP Server 的職責限於：tool 定義、參數映射、結果格式化
- SDK 負責：HTTP 調用、錯誤處理、型別安全

詳見 [architecture-decisions.md](./architecture-decisions.md) AD-2。

---

## 現狀矩陣

### 已完成黃金標準

| 服務 | SDK | CLI | MCP | Skill |
|------|-----|-----|-----|-------|
| agent-metrics | `agent_metrics.py` | `maestro.py` | 10 工具 | maestro |
| sandbox-executor | `sandbox.py` | `sandbox.py` | 2 工具 | sandbox-patterns |
| hook-observatory | `hook_observatory.py` | `cso.py` | 3 工具 | — |
| tmux-relay | `tmux_relay.py` | `relay.py` | 6 工具 | tmux-relay |
| memvault | `memvault.py` | `memvault.py` | 8 工具 | memvault |

### 核心模組進度

| 模組 | HTTP API | SDK | CLI | MCP | Skill |
|------|----------|-----|-----|-----|-------|
| finance | ✅ | ❌ | ❌ | ✅ (3 伺服器) | ✅ |
| taskflow | ✅ | ❌ | ❌ | ✅ | ❌ |
| intelflow | ✅ | ❌ | ❌ | 🔶 (2 工具) | ✅ |
| nodeflow | ✅ | ❌ | ❌ | ✅ | ✅ |
| notification | ✅ | ❌ | ❌ | ❌ | ❌ |
| auth | ✅ | ❌ | ❌ | ❌ | ❌ |
| admin | ✅ | ❌ | ❌ | ❌ | ❌ |

### 工作站進度

| 工作站 | HTTP API | SDK | CLI | MCP | Skill |
|--------|----------|-----|-----|-----|-------|
| sentinel | ✅ | ❌ | ❌ | ✅ | ✅ |
| system-monitor | ✅ | ❌ | ❌ | ✅ | ✅ (system-map) |
| envkit | ❌ | ❌ | ✅ | ✅ | ✅ |
| tmux-webui | ✅+WS | ❌ | ❌ | ✅ | ✅ (tmux-expert) |
| session-archiver | 🔶 | ❌ | ❌ | ❌ | ❌ |

---

## 演進計劃

三波推進策略，詳見 [composite-architecture-roadmap.md](../plans/composite-architecture-roadmap.md)。

| 波次 | 目標 | 服務 |
|------|------|------|
| P1 | 高價值日常使用 | finance, intelflow, sentinel |
| P2 | 基礎設施與知識 | nodeflow, system-monitor, envkit |
| P3 | 支援服務 | notification, auth, admin, tmux-webui, session-archiver |

---

## 相關文件

| 文件 | 用途 |
|------|------|
| [architecture-decisions.md](./architecture-decisions.md) AD-2 | MCP Server 作為 SDK Adapter 的設計理由 |
| [../plans/composite-architecture-roadmap.md](../plans/composite-architecture-roadmap.md) | 三波推進的具體實作計劃 |
| [../vision/domain-catalog.md](../vision/domain-catalog.md) | 統一服務目錄（含四層狀態） |
| [tech-stack.md](./tech-stack.md) | 技術選型 |
