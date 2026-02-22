# Frontend Architecture Guide

## Design Principles

### 1. Single Application, Domain Modules

One React application with domain-based module organization. No Module Federation, no micro-frontends -- just clean code splitting with `React.lazy`.

```
apps/web/                     Single React App
├── src/
│   ├── shell/                App shell (layout, nav, auth)
│   ├── modules/              Domain UI modules
│   │   ├── auth/
│   │   ├── finance/
│   │   ├── quest/
│   │   ├── muse/
│   │   └── admin/
│   ├── plugins/              Plugin UI runtime
│   └── shared/               Shared components, hooks, utils
```

**Why single app over micro-frontends:**
- Simpler build and deploy pipeline (one build, one artifact)
- No Module Federation complexity or version conflicts
- Shared state and routing are trivial (same React tree)
- Code splitting via `React.lazy` provides equivalent lazy-loading
- Aligns with backend modular monolith philosophy

### 2. Domain Module Structure

Each module in `src/modules/<domain>/` follows a consistent layout:

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

- Modules **may** import from `src/shared/`
- Modules **must not** import from other modules directly
- Cross-module interaction goes through:
  - **Router** (navigation via URL)
  - **Custom events** (cross-module notifications via EventEmitter)
  - **Shared stores** in `src/shared/stores/` (auth context, user state)

## Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Build | Rsbuild | Rspack-based, fast builds |
| Framework | React 19 | Component model, ecosystem, concurrent features |
| Routing | React Router 7 | Lazy loading, nested routes |
| Styling | Tailwind CSS 4 | Utility-first, consistent design tokens |
| State | Zustand 5 | Lightweight, per-module scoped |
| Types | TypeScript 5 | Strict mode, shared types via `src/shared/types/` |

## App Shell (`src/shell/`)

The shell provides the application frame:

```
src/shell/
├── App.tsx                  Root component
├── Layout.tsx               Header, sidebar, content area
├── Router.tsx               Top-level routes with lazy loading
├── AuthProvider.tsx         Auth context, session management
└── ThemeProvider.tsx         Dark/light mode, CSS variables
```

### Routing with Code Splitting

```typescript
// src/shell/Router.tsx
import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";

const Finance = lazy(() => import("../modules/finance"));
const Quest = lazy(() => import("../modules/quest"));
const Muse = lazy(() => import("../modules/muse"));
const Admin = lazy(() => import("../modules/admin"));

export function Router() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/finance/*" element={<Finance />} />
        <Route path="/quest/*" element={<Quest />} />
        <Route path="/muse/*" element={<Muse />} />
        <Route path="/admin/*" element={<Admin />} />
        <Route path="/settings/*" element={<Settings />} />
      </Routes>
    </Suspense>
  );
}
```

Each module handles its own sub-routing internally.

## Routing Convention

| Pattern | Owner |
|---------|-------|
| `/` | Shell (dashboard) |
| `/finance/*` | Finance module |
| `/quest/*` | Quest module |
| `/muse/*` | Muse module |
| `/admin/*` | Admin module |
| `/settings/*` | Shell (global settings) |

## API Communication

All modules talk to the same backend (Core Monolith on port 8800):

```
apps/web/  →  services/core/  (port 8800)
```

API calls are routed through the Gateway (Nginx) in production:

```
Production:  https://domain.com/api/finance/  → nginx → core monolith
Development: http://localhost:8800/api/finance/ → direct
```

Each module has its own `api/client.ts` that wraps fetch calls for its domain endpoints.

## Plugin UI Slots

Plugins can inject UI components into predefined slots in the application:

```typescript
// src/plugins/PluginSlot.tsx
interface PluginSlotProps {
  name: string;       // e.g., "finance.dashboard.sidebar"
  context?: unknown;  // data passed to plugin components
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

Available slots follow the pattern `{module}.{page}.{position}`:

| Slot | Location |
|------|----------|
| `finance.dashboard.sidebar` | Finance dashboard sidebar |
| `quest.detail.actions` | Quest detail page action buttons |
| `shell.header.right` | Global header right section |
| `shell.sidebar.bottom` | Global sidebar bottom section |

See [Plugin System](./plugin-system.md) for details.

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
├── stores/                  Global stores (auth, theme)
│   ├── authStore.ts
│   └── themeStore.ts
├── types/                   Shared TypeScript types
│   ├── user.ts
│   └── api.ts
└── utils/                   Utility functions
```

Import in any module:
```typescript
import { Button } from "@/shared/components/Button";
import { useAuth } from "@/shared/hooks/useAuth";
```

## Build & Deploy

Single build, single artifact:

```bash
cd apps/web && pnpm build    # → dist/ with index.html + chunks
```

Production: Nginx serves `dist/index.html`. Code-split chunks are loaded on demand per route.

Development:
```bash
cd apps/web && pnpm dev      # → http://localhost:3000
```

Rsbuild config proxies `/api/*` to the Core Monolith during development.
