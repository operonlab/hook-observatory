---
doc_version: 3
content_hash: d08da8ad
source_version: 3
target_lang: en
translated_at: 2026-02-24
source_hash: 5c0da808
source_lang: zh-TW
---

# Frontend Architecture Guide

## Three-Layer Frontend Architecture

The Workshop Frontend is a Single React App, composed of three coexisting layers:

| Layer | Name | Description |
|------|------|------|
| **Layer 1** | Module SPA Pages | Each module has complete routing and UI (`/finance/*`, `/quest/*`, etc.) |
| **Layer 2** | Dashboard Widgets | Homepage dashboard, widgets drawn from various modules can be dragged and combined (`/`) |
| **Layer 3** | LLM Chat Overlay | A global chat interface, floating on top, similar to Google Gemini embedded in Chrome |

Layer 2 **complements** Layer 1 (it does not replace module pages). Layer 3 spans all pages.

## Design Principles

### 1. Single Application, Domain Modules

A React application with modules organized in a domain-centric manner. It does not use Module Federation or micro-frontends — only clean code splitting via `React.lazy`.

```
workbench/                    Single React App
├── src/
│   ├── shell/                Application Shell (layout, navigation, authentication, LLM Chat Overlay)
│   ├── modules/              Domain UI Modules (10 core modules)
│   │   ├── auth/
│   │   ├── finance/
│   │   ├── quest/
│   │   ├── muse/
│   │   ├── scout/
│   │   ├── lore/
│   │   ├── dojo/
│   │   ├── roster/
│   │   ├── nexus/
│   │   └── admin/
│   ├── chat/                 LLM Chat Overlay (Layer 3)
│   ├── widgets/              Workbench Widget Component Library (Layer 2)
│   ├── plugins/              Plugin UI Runtime
│   └── shared/               Shared Components, Hooks, Utility Functions
```

**Why choose a single application over micro-frontends:**
- Simpler build and deployment pipeline (one build, one artifact)
- No Module Federation complexity or version conflict issues
- Sharing state and routing is very straightforward (within the same React tree)
- Code splitting via `React.lazy` provides equivalent lazy loading effects
- Consistent with the modular monolith philosophy of the backend

### 2. Domain Module Structure

Each module located in `src/modules/<domain>/` follows a consistent layout:

```
src/modules/<domain>/
├── components/              Domain-specific components
│   └── <Component>.tsx
├── pages/                   Route-level components
│   └── <Page>.tsx
├── hooks/                   Domain-specific hooks
├── stores/                  Zustand stores (domain-scoped)
├── api/                     API client functions
│   └── client.ts
├── types/                   Domain-specific types
└── index.tsx                Module entry (exports routes)
```

### 3. Module Boundary Rules

- Modules **can** import from `src/shared/`
- Modules **must never** import directly from other modules
- Cross-module interaction must happen via:
  - **Router** (navigation via URL)
  - **Custom Events** (cross-module notification via EventEmitter)
  - **Shared Stores** in `src/shared/stores/` (authentication context, user state)

## Tech Stack

See [tech-stack.md](./tech-stack.md#前端) for details.

## Application Shell (`src/shell/`)

The Shell provides the application framework:

```
src/shell/
├── App.tsx                  Root component
├── Layout.tsx               Header, sidebar, content area
├── Router.tsx               Top-level routes with lazy loading
├── AuthProvider.tsx         Authentication context, session management
└── ThemeProvider.tsx         Dark/light mode, CSS variables
```

### Routes with Code Splitting

```typescript
// src/shell/Router.tsx
import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";

// Phase 1
const Finance = lazy(() => import("../modules/finance"));
const Quest = lazy(() => import("../modules/quest"));
const Muse = lazy(() => import("../modules/muse"));
const Admin = lazy(() => import("../modules/admin"));
// Phase 2
const Scout = lazy(() => import("../modules/scout"));
const Lore = lazy(() => import("../modules/lore"));
const Dojo = lazy(() => import("../modules/dojo"));
// Phase 3
const Roster = lazy(() => import("../modules/roster"));
const Nexus = lazy(() => import("../modules/nexus"));

export function Router() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        {/* Phase 1 */}
        <Route path="/finance/*" element={<Finance />} />
        <Route path="/quest/*" element={<Quest />} />
        <Route path="/muse/*" element={<Muse />} />
        <Route path="/admin/*" element={<Admin />} />
        {/* Phase 2 */}
        <Route path="/scout/*" element={<Scout />} />
        <Route path="/lore/*" element={<Lore />} />
        <Route path="/dojo/*" element={<Dojo />} />
        {/* Phase 3 */}
        <Route path="/roster/*" element={<Roster />} />
        <Route path="/nexus/*" element={<Nexus />} />
        <Route path="/settings/*" element={<Settings />} />
      </Routes>
    </Suspense>
  );
}
```

Each module internally handles its sub-routes.

> **`/` (Dashboard)** is the Widget dashboard view, combining summary widgets extracted from various modules. The complete UI for each module is under routes like `/finance/*`, `/quest/*`, etc.

## Routing Conventions

| Path Pattern | Responsible Party | Phase |
|---------|-------|-------|
| `/` | Shell (Dashboard) | 1 |
| `/finance/*` | Finance Module | 1 |
| `/quest/*` | Quest Module | 1 |
| `/muse/*` | Muse Module | 1 |
| `/admin/*` | Admin Module | 1 |
| `/scout/*` | Scout Module | 2 |
| `/lore/*` | Lore Module | 2 |
| `/dojo/*` | Dojo Module | 2 |
| `/roster/*` | Roster Module | 3 |
| `/nexus/*` | Nexus Module | 3 |
| `/settings/*` | Shell (Global Settings) | 1 |

## API Communication

All modules communicate with the same backend (Core Monolith on port 8800):

```
workbench/  →  core/  (port 8800)
```

In production, API calls are routed via a gateway (Nginx):

```
Production:  https://domain.com/api/finance/  → nginx → core monolith
Development:  http://localhost:8800/api/finance/ → Direct call
```

Each module has its own `api/client.ts` to encapsulate fetch calls for its domain endpoints.

## Plugin UI Slots

Plugins can inject UI components into predefined slots in the application:

```typescript
// src/plugins/PluginSlot.tsx
interface PluginSlotProps {
  name: string;       // e.g., "finance.dashboard.sidebar"
  context?: unknown;  // Data passed to the plugin component
}

export function PluginSlot({ name, context }: PluginSlotProps) {
  const plugins = usePluginSlot(name);
  return (
    <>
      {plugins.map((plugin) => (
        <plugin.Component key={plugin.id} context={context} />
      ))}
    </>
  );
}
```

For a complete list of slots, refer to [Plugin System](./plugin-system.md#ui-插槽).

## Shared Components (`src/shared/`)

```
src/shared/
├── components/              Reusable UI components
│   ├── Button.tsx
│   ├── Modal.tsx
│   ├── DataTable.tsx
│   └── ...
├── hooks/                   Shared React hooks
│   ├── useAuth.ts
│   ├── useApi.ts
│   └── ...
├── stores/                  Global stores (authentication, theme)
│   ├── authStore.ts
│   └── themeStore.ts
├── types/                   Shared TypeScript types
│   ├── user.ts
│   └── api.ts
└── utils/                   Utility functions
```

Import in any module:
```typescript
import { Button } from " @/shared/components/Button";
import { useAuth } from " @/shared/hooks/useAuth";
```

## Build and Deployment

Single build, single artifact:

```bash
cd workbench && pnpm build   # → dist/ directory containing index.html and chunks
```

Production: `dist/index.html` is served by Nginx. Code-split chunks are loaded as needed by routing.

Development:
```bash
cd workbench && pnpm dev     # → http://localhost:3000
```

Rsbuild configuration proxies `/api/*` to the Core Monolith during development.

## LLM Chat Overlay (Layer 3)

A global LLM chat interface, floating on top of all pages, similar to Google's Gemini Chat embedded in Chrome.

```
┌──────────────────────────────────────┐
│  Any Page (/finance, /quest, ...)     │
│                                      │
│                  ┌───────────────────┐│
│                  │  LLM Chat Panel  ││ ← Overlay, collapsible/expandable
│                  │  ─────────────── ││
│                  │  User: Last month...││
│                  │  LLM: Based on records...││
│                  │  [Input Box]        ││
│                  └────────────────────┘│
└───────────────────────────────────────┘
```

**Features**:
- Chat with LLM without leaving the current page
- Context-aware of the current page (e.g., can directly ask finance questions when on the finance page)
- Stream LLM responses via SSE
- Collapsible/expandable, does not interfere with main operations
```
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2605ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2627ms
