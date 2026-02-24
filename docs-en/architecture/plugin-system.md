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
|--------|---------------|
| **Stable Diffusion WebUI** | Extension list, Hook-based lifecycle, Git-based installation |
| **Obsidian** | Plugin settings UI, Sandboxed execution, Community plugin library |
| **VS Code** | Contribution points (UI slots), Activation events, Permission model |

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
|-------|----------|-------------|
| `id` | Yes | Unique plugin identifier (kebab-case) |
| `name` | Yes | Human-readable name |
| `version` | Yes | SemVer version |
| `description` | Yes | Short description |
| `author` | Yes | Author or organization |
| `repository` | Yes | Git repository URL |
| `permissions` | Yes | Required permissions (intersected with user permissions) |
| `hooks` | No | Backend hook registrations |
| `ui_slots` | No | Frontend UI slot registrations |
| `settings` | No | Plugin configuration schema |
| `activationEvents` | No | Events that trigger plugin loading |
| `minCoreVersion` | No | Minimum compatible core version |

## Hook Lifecycle

Hooks follow a `before_*` / `after_*` pattern:

```
Request arrives
    │
    ▼
before_{action}  ← Plugin can validate, modify, or reject
    │
    ▼
Core action executes
    │
    ▼
after_{action}   ← Plugin can extend, log, or trigger side effects
    │
    ▼
Response is sent
```

### Available Hooks

| Hook | When | Modifiable | Rejectable |
|------|--------|-----------|------------|
| `before_transaction_create` | Before inserting a transaction | Yes (data) | Yes |
| `after_transaction_create` | After a transaction is committed | No | No |
| `before_quest_complete` | Before marking a quest as complete | Yes (data) | Yes |
| `after_quest_complete` | After a quest is marked complete | No | No |
| `before_spark_create` | Before creating a Spark | Yes (data) | Yes |
| `after_spark_create` | After a Spark is committed | No | No |
| `before_user_approve` | Before an admin approves a user | Yes (data) | Yes |
| `after_user_approve` | After a user is approved | No | No |
| `on_startup` | Application startup | No | No |
| `on_shutdown` | Application shutdown | No | No |

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
# from huggingface_hub.dataclasses import dataclass
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

## Plugin Installation

### Git-based Installation

Plugins are installed from Git repositories:

```bash
# CLI (Future)
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
1. Clone repository into core/plugins/<plugin-id>/
2. Validate plugin.json manifest
3. Check for permission compatibility
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

1.  Plugins **cannot** access modules beyond their declared permissions.
2.  Plugins **cannot** elevate to a level beyond the current user's permissions.
3.  Admin-only plugins require `admin.*` permissions in their manifest.
4.  Permission violations are logged, and the action is rejected.

### Example

```
Plugin declares: ["finance.read", "finance.write", "quest.read"]

Admin user (has all permissions):
  → Plugin gets: finance.read, finance.write, quest.read

Regular user (has finance.*, quest.*):
  → Plugin gets: finance.read, finance.write, quest.read

Guest user (has only *.read):
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
// In the finance dashboard
import { PluginSlot } from "@/plugins/PluginSlot";

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
|-----------|----------|-----------------|
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

Start with the least privilege. Only expand when necessary.

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
# Copy plugin into the core plugins directory
cp -r my-plugin/ ~/workshop/core/plugins/my-plugin/

# Restart the core to load the new plugin
# Plugin hooks will be registered automatically on startup
```

### 6. Publish

```bash
git init && git add . && git commit -m "Initial plugin release"
git remote add origin https://github.com/you/my-plugin
git push -u origin main
git tag v1.0.0 && git push --tags
```

## Hook Engine Internals

```python
class HookEngine:
    """Manages plugin hook registration and execution."""

    def __init__(self):
        self._hooks: dict[str, list[PluginHook]] = defaultdict(list)

    def register(self, plugin_id: str, hook_name: str, handler: Callable):
        self._hooks[hook_name].append(PluginHook(plugin_id, handler))

    async def run_before(self, hook_name: str, context: HookContext) -> HookResult:
        """Run all before_* hooks. Any REJECT stops the chain."""
        for hook in self._hooks.get(hook_name, []):
            if not self._has_permission(hook.plugin_id, context.user):
                continue
            result = await hook.handler(context)
            if result == HookResult.REJECT:
                return result
            if result.data:
                context.data = result.data  # Apply modifications
        return HookResult.CONTINUE(data=context.data)

    async def run_after(self, hook_name: str, context: HookContext):
        """Run all after_* hooks. Fire-and-forget."""
        for hook in self._hooks.get(hook_name, []):
            if not self._has_permission(hook.plugin_id, context.user):
                continue
            asyncio.create_task(hook.handler(context))
```

## Future Outlook

-   **Plugin Marketplace**: A web UI for browsing and installing community plugins
-   **Plugin Sandboxing**: Process-level isolation for untrusted plugins
-   **Plugin Dependencies**: Allow plugins to depend on other plugins
-   **Plugin API Versioning**: A stable hook API with deprecation warnings
-   **Hot Reloading**: Reload plugin code without restarting the core
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2517ms
