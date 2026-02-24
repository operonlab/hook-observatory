---
doc_version: 2
content_hash: cbc859ec
source_version: 2
target_lang: en
translated_at: 2026-02-24
source_hash: b0ac1680
source_lang: zh-TW
---

# Plugin System Architecture

## Design Inspiration

The plugin system borrows from three proven models:

| Source | Borrowed Aspects |
|---|---|
| **Stable Diffusion WebUI** | Extension list, hook-based lifecycle, Git-based installation |
| **Obsidian** | Plugin settings UI, sandboxed execution, community plugin library |
| **VS Code** | Contribution points (UI slots), activation events, permission model |

## Plugin Manifest

Each plugin declares itself via `plugin.json`:

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

### Manifest Fields

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Unique plugin identifier (kebab-case) |
| `name` | Yes | Human-readable name |
| `version` | Yes | SemVer version |
| `description` | Yes | Short description |
| `author` | Yes | Author or organization |
| `repository` | Yes | Git repository URL |
| `permissions` | Yes | Required permissions (intersected with user permissions) |
| `hooks` | No | Backend hook registration |
| `ui_slots` | No | Frontend UI slot registration |
| `settings` | No | Plugin configuration structure (Schema) |
| `activationEvents` | No | Events that trigger plugin loading |
| `minCoreVersion` | No | Minimum compatible core version |

## Hook Lifecycle

Hooks follow the `before_*` / `after_*` pattern:

```
Request Arrives
    │
    ▼
before_{action}  ← Plugin can validate, modify, or reject
    │
    ▼
Core Action Executes
    │
    ▼
after_{action}   ← Plugin can extend, log, or trigger side effects
    │
    ▼
Response is Sent
```

### Available Hooks

| Hook | Timing | Modifiable | Rejectable |
|---|---|---|---|
| `before_transaction_create` | Before transaction insertion | Yes (data) | Yes |
| `after_transaction_create` | After transaction is committed | No | No |
| `before_quest_complete` | Before marking quest complete | Yes (data) | Yes |
| `after_quest_complete` | After quest is marked complete | No | No |
| `before_spark_create` | Before Spark creation | Yes (data) | Yes |
| `after_spark_create` | After Spark is committed | No | No |
| `before_user_approve` | Before admin approves user | Yes (data) | Yes |
| `after_user_approve` | After user is approved | No | No |
| `on_startup` | On application startup | No | No |
| `on_shutdown` | On application shutdown | No | No |

### Hook Implementation

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
 @.cache/uv/archive-v0/uj_7CuQMD1gog0o_f4ybB/huggingface_hub/dataclasses.py
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

## Plugin Installation

### Git-based Installation

Plugins are installed from Git repositories:

```bash
# CLI (future)
workshop plugin install https://github.com/workshop-plugins/expense-categorizer

# API
POST /api/admin/plugins/install
{
  "repository": "https://github.com/workshop-plugins/expense-categorizer",
  "version": "1.0.0"
}
```

### Installation Process

```
1. Clone repository to core/plugins/<plugin-id>/
2. Validate the plugin.json manifest
3. Check permission compatibility
4. Register hooks with the Hook Engine
5. Register UI slots with the frontend runtime
6. Publish event: admin.plugin.installed
```

### Plugin Directory Structure

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

## Permission Isolation

Plugins operate in a **permission sandbox**:

```
effective_permissions = plugin.manifest.permissions ∩ current_user.permissions
```

### Rules

1. A plugin **cannot** access modules beyond its declared permissions.
2. A plugin **cannot** escalate to a level beyond the current user's permissions.
3. Admin-only plugins must have `admin.*` permissions in the manifest.
4. Permission violations are logged, and the action is rejected.

### Example

```
Plugin declares: ["finance.read", "finance.write", "quest.read"]

Admin user (has all permissions):
  → Plugin gets: finance.read, finance.write, quest.read

Regular user (has finance.*, quest.*):
  → Plugin gets: finance.read, finance.write, quest.read

Guest user (only has *.read):
  → Plugin gets: finance.read, quest.read
  → finance.write is silently excluded
```

## UI Slots

Plugins inject frontend components into predefined slots:

### Slot Registration

In `plugin.json`:
```json
{
  "ui_slots": {
    "finance.dashboard.sidebar": "frontend/components/CategoryBreakdown.tsx"
  }
}
```

### Slot Rendering

```typescript
// In the Finance Dashboard
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

### Available Slots

| Slot Name | Location | Provided Context |
|---|---|---|
| `shell.header.right` | Global header, right side | `{ user }` |
| `shell.sidebar.bottom` | Global sidebar, bottom | `{ user }` |
| `finance.dashboard.sidebar` | Finance dashboard sidebar | `{ userId }` |
| `finance.transaction.detail` | Transaction detail panel | `{ transaction }` |
| `quest.detail.actions` | Quest detail actions area | `{ quest }` |
| `muse.spark.toolbar` | Spark editor toolbar | `{ spark }` |

## Plugin Development Guide

### 1. Create Plugin Scaffold

```bash
mkdir my-plugin && cd my-plugin
```

```
my-plugin/
├── plugin.json
├── backend/
│   └── hooks.py
├── frontend/           # Optional
│   └── components/
└── README.md
```

### 2. Define Manifest

Start with the least privilege. Expand only when necessary.

### 3. Implement Hooks

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

### 4. Add Frontend Components (Optional)

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

### 5. Local Testing

```bash
# Copy the plugin to the core
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2611ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2467ms
