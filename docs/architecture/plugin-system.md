---
doc_version: 2
content_hash: cbc859ec
source_version: 2
target_lang: zh-TW
translated_at: 2026-02-23
---

# 插件系統架構

## 設計靈感

插件系統借鑑了三個經過驗證的模型：

| 來源 | 借用部分 |
|--------|---------------|
| **Stable Diffusion WebUI** | 擴充清單、基於 Hook 的生命週期、基於 Git 的安裝方式 |
| **Obsidian** | 插件設定 UI、沙盒化執行、社群插件庫 |
| **VS Code** | 貢獻點 (UI 插槽)、啟動事件、權限模型 |

## 插件清單 (Manifest)

每個插件都透過 `plugin.json` 聲明自身：

```json
{
  "id": "expense-categorizer",
  "name": "Smart Expense Categorizer",
  "version": "1.0.0",
  "description": "Automatically categorizes transactions using AI",
  "author": "workshop-plugins",
  "repository": "https://github.com/workshop-plugins/expense-categorizer",

  "permissions": [
    "finance.read",
    "finance.write"
  ],

  "hooks": {
    "before_transaction_create": "backend/hooks.py:before_transaction_create",
    "after_transaction_create": "backend/hooks.py:after_transaction_create"
  },

  "ui_slots": {
    "finance.dashboard.sidebar": "frontend/components/CategoryBreakdown.tsx"
  },

  "settings": {
    "model": {
      "type": "string",
      "default": "gpt-4o-mini",
      "description": "AI model for categorization"
    },
    "auto_categorize": {
      "type": "boolean",
      "default": true,
      "description": "Automatically categorize new transactions"
    }
  },

  "activationEvents": [
    "finance.transaction.created"
  ],

  "minCoreVersion": "0.1.0"
}
```

### 清單欄位

| 欄位 | 必填 | 描述 |
|-------|----------|-------------|
| `id` | 是 | 唯一的插件識別碼 (kebab-case) |
| `name` | 是 | 可讀名稱 |
| `version` | 是 | SemVer 版本 |
| `description` | 是 | 簡短描述 |
| `author` | 是 | 作者或組織 |
| `repository` | 是 | Git 儲存庫 URL |
| `permissions` | 是 | 所需權限（與使用者權限取交集） |
| `hooks` | 否 | 後端 Hook 註冊 |
| `ui_slots` | 否 | 前端 UI 插槽註冊 |
| `settings` | 否 | 插件配置結構 (Schema) |
| `activationEvents` | 否 | 觸發插件載入的事件 |
| `minCoreVersion` | 否 | 最低相容核心版本 |

## Hook 生命週期

Hook 遵循 `before_*` / `after_*` 模式：

```
請求到達
    │
    ▼
before_{action}  ← 插件可以驗證、修改或拒絕
    │
    ▼
核心動作執行
    │
    ▼
after_{action}   ← 插件可以擴展、記錄或觸發副作用
    │
    ▼
回應已發送
```

### 可用 Hook

| Hook | 時機 | 可修改 | 可拒絕 |
|------|--------|-----------|------------|
| `before_transaction_create` | 插入交易前 | 是 (數據) | 是 |
| `after_transaction_create` | 交易提交後 | 否 | 否 |
| `before_quest_complete` | 標記任務完成前 | 是 (數據) | 是 |
| `after_quest_complete` | 任務標記完成後 | 否 | 否 |
| `before_spark_create` | 建立 Spark 前 | 是 (數據) | 是 |
| `after_spark_create` | Spark 提交後 | 否 | 否 |
| `before_user_approve` | 管理員批准使用者前 | 是 (數據) | 是 |
| `after_user_approve` | 使用者獲批准後 | 否 | 否 |
| `on_startup` | 應用程式啟動 | 否 | 否 |
| `on_shutdown` | 應用程式關閉 | 否 | 否 |

### Hook 實作

```python
# plugins/expense-categorizer/backend/hooks.py

async def before_transaction_create(context: HookContext) -> HookResult:
    """Auto-categorize transaction before it's saved."""
    if not context.plugin_settings.get("auto_categorize"):
        return HookResult.PASS

    data = context.data
    if not data.get("category"):
        category = await ai_categorize(data["description"], data["amount"])
        data["category"] = category

    return HookResult.CONTINUE(data=data)


async def after_transaction_create(context: HookContext) -> None:
    """Log categorization result for analytics."""
    await log_categorization(
        transaction_id=context.data["transaction_id"],
        category=context.data.get("category"),
        was_auto=True,
    )
```

### HookContext

```python
 @dataclass
class HookContext:
    event_type: str              # The hook being called
    data: dict                   # Mutable data (for before_* hooks)
    user: AuthUser               # Current user
    plugin_settings: dict        # This plugin's settings values
    event_bus: EventBus          # For publishing follow-up events
```

### HookResult

```python
class HookResult:
    PASS = ...       # Skip this hook, let others run
    CONTINUE = ...   # Continue with (optionally modified) data
    REJECT = ...     # Reject the action (before_* only), returns 400 to client
```

## 插件安裝

### 基於 Git 的安裝

插件從 Git 儲存庫安裝：

```bash
# CLI (未來)
workshop plugin install https://github.com/workshop-plugins/expense-categorizer

# API
POST /api/admin/plugins/install
{
  "repository": "https://github.com/workshop-plugins/expense-categorizer",
  "version": "1.0.0"
}
```

### 安裝流程

```
1. 將儲存庫複製到 core/plugins/<plugin-id>/
2. 驗證 plugin.json 清單
3. 檢查權限相容性
4. 向 Hook 引擎註冊 Hook
5. 向前端執行階段註冊 UI 插槽
6. 發布事件：admin.plugin.installed
```

### 插件目錄結構

```
core/plugins/
├── expense-categorizer/
│   ├── plugin.json
│   ├── backend/
│   │   └── hooks.py
│   ├── frontend/
│   │   └── components/
│   │       └── CategoryBreakdown.tsx
│   └── README.md
└── daily-summary/
    ├── plugin.json
    ├── backend/
    │   └── hooks.py
    └── README.md
```

## 權限隔離

插件在**權限沙盒**中運作：

```
effective_permissions = plugin.manifest.permissions ∩ current_user.permissions
```

### 規則

1. 插件**不能**存取超出其聲明權限的模組
2. 插件**不能**提升到超過當前使用者權限的級別
3. 僅限管理員的插件需要在清單中具有 `admin.*` 權限
4. 權限違規會被記錄，且該動作將被拒絕

### 範例

```
插件聲明：["finance.read", "finance.write", "taskflow.read"]

管理員使用者（擁有所有權限）：
  → 插件獲得：finance.read, finance.write, taskflow.read

一般使用者（擁有 finance.*, taskflow.*）：
  → 插件獲得：finance.read, finance.write, taskflow.read

訪客使用者（僅具有 *.read）：
  → 插件獲得：finance.read, taskflow.read
  → finance.write 會被靜默排除
```

## UI 插槽

插件將前端組件注入預定義的插槽中：

### 插槽註冊

在 `plugin.json` 中：
```json
{
  "ui_slots": {
    "finance.dashboard.sidebar": "frontend/components/CategoryBreakdown.tsx"
  }
}
```

### 插槽渲染

```typescript
// 在財務儀表板中
import { PluginSlot } from " @/plugins/PluginSlot";

export function FinanceDashboard() {
  return (
    <div className="flex">
      <main>
        <TransactionList />
      </main>
      <aside>
        <PluginSlot name="finance.dashboard.sidebar" context={{ userId }} />
      </aside>
    </div>
  );
}
```

### 可用插槽

| 插槽名稱 | 位置 | 提供的上下文 (Context) |
|-----------|----------|-----------------|
| `shell.header.right` | 全域頂欄，右側 | `{ user }` |
| `shell.sidebar.bottom` | 全域側邊欄，底部 | `{ user }` |
| `finance.dashboard.sidebar` | 財務儀表板側邊欄 | `{ userId }` |
| `finance.transaction.detail` | 交易詳情面板 | `{ transaction }` |
| `taskflow.detail.actions` | 任務詳情動作區域 | `{ taskflow }` |
| `ideagraph.spark.toolbar` | Spark 編輯器工具列 | `{ spark }` |

## 插件開發指南

### 1. 建立插件腳手架

```bash
mkdir my-plugin && cd my-plugin
```

```
my-plugin/
├── plugin.json
├── backend/
│   └── hooks.py
├── frontend/           # 選填
│   └── components/
└── README.md
```

### 2. 定義清單

從最小權限開始。僅在需要時擴展。

### 3. 實作 Hook

```python
# backend/hooks.py

async def after_transaction_create(context: HookContext) -> None:
    """React to new transactions."""
    amount = context.data.get("amount", 0)
    if amount > 10000:
        await context.event_bus.publish(
            "plugin.expense_categorizer.large_transaction_detected",
            data={"transaction_id": context.data["transaction_id"], "amount": amount},
            user_id=context.user.id,
        )
```

### 4. 添加前端組件（選填）

```typescript
// frontend/components/CategoryBreakdown.tsx
interface Props {
  context: { userId: string };
}

export function CategoryBreakdown({ context }: Props) {
  const { data } = usePluginApi("/api/plugins/expense-categorizer/breakdown", {
    userId: context.userId,
  });
  return <PieChart data={data} />;
}
```

### 5. 本地測試

```bash
# 將插件複製到核心插件目錄
cp -r my-plugin/ ~/workshop/core/plugins/my-plugin/

# 重啟核心以載入新插件
# 插件 Hook 將在啟動時自動註冊
```

### 6. 發布

```bash
git init && git add . && git commit -m "Initial plugin release"
git remote add origin https://github.com/you/my-plugin
git push -u origin main
git tag v1.0.0 && git push --tags
```

## Hook 引擎內部機制

```python
class HookEngine:
    """管理插件 Hook 的註冊與執行。"""

    def __init__(self):
        self._hooks: dict[str, list[PluginHook]] = defaultdict(list)

    def register(self, plugin_id: str, hook_name: str, handler: Callable):
        self._hooks[hook_name].append(PluginHook(plugin_id, handler))

    async def run_before(self, hook_name: str, context: HookContext) -> HookResult:
        """執行所有 before_* Hook。任何 REJECT 都會停止鏈條。"""
        for hook in self._hooks.get(hook_name, []):
            if not self._has_permission(hook.plugin_id, context.user):
                continue
            result = await hook.handler(context)
            if result == HookResult.REJECT:
                return result
            if result.data:
                context.data = result.data  # 套用修改
        return HookResult.CONTINUE(data=context.data)

    async def run_after(self, hook_name: str, context: HookContext):
        """執行所有 after_* Hook。即發即棄 (Fire-and-forget)。"""
        for hook in self._hooks.get(hook_name, []):
            if not self._has_permission(hook.plugin_id, context.user):
                continue
            asyncio.create_task(hook.handler(context))
```

## 未來展望

- **插件市場**：用於瀏覽和安裝社群插件的 Web UI
- **插件沙盒化**：針對不信任插件的程序級隔離
- **插件依賴**：允許插件依賴於其他插件
- **插件 API 版本控制**：具有棄用警告的穩定 Hook API
- **熱重載**：無需重啟核心即可重新載入插件程式碼
