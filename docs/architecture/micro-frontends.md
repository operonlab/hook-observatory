# Micro Frontends Architecture Guide

## Design Principles

### 1. Independent Deployability
Each micro frontend (MFE) is a standalone React application that can be built, tested, and deployed independently.

### 2. Shell + Remotes Pattern
One **shell** (host) app loads multiple **remote** MFE apps at runtime via Module Federation.

```
apps/shell/          → Host app (layout, navigation, auth context)
apps/finance/        → Remote MFE (loaded on demand)
apps/quest/          → Remote MFE (loaded on demand)
apps/muse/           → Remote MFE (loaded on demand)
```

### 3. Zero Shared State
MFEs communicate through:
- **URL/Router** — navigation state
- **Custom Events** — cross-MFE notifications
- **Shared Context** — auth/user context provided by shell

**Never** share Redux/Zustand stores across MFEs.

## Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Build | Rsbuild | Rspack-based, fast, Module Federation v2 native |
| Framework | React 19 | Component model, ecosystem |
| Routing | React Router | Per-MFE routing, shell handles top-level |
| Styling | Tailwind CSS | Utility-first, no CSS conflicts between MFEs |
| State | Zustand | Lightweight, per-MFE scoped |
| Types | TypeScript | Strict mode, shared types from `libs/typescript/` |

## App Template

```
apps/<name>/
├── src/
│   ├── components/          # Domain-specific components
│   │   └── <Component>.tsx
│   ├── pages/               # Route-level components
│   │   └── <Page>.tsx
│   ├── hooks/               # Domain-specific hooks
│   ├── stores/              # Zustand stores (domain-scoped)
│   ├── api/                 # API client functions
│   │   └── client.ts        # httpx/fetch wrapper for this domain's backend
│   ├── types/               # Domain-specific types
│   ├── App.tsx              # MFE root component
│   ├── bootstrap.tsx        # Module Federation bootstrap
│   └── index.tsx            # Entry point
├── public/
├── rsbuild.config.ts        # Rsbuild + Module Federation config
├── package.json
├── tsconfig.json
└── README.md
```

## Shell App (Host)

The shell is responsible for:
1. **Layout** — header, sidebar, navigation
2. **Auth** — login/logout, token management, auth context
3. **Routing** — top-level route → lazy-load correct MFE
4. **Theme** — global CSS variables, dark/light mode

```typescript
// apps/shell/src/routes.tsx
const Finance = lazy(() => import("finance/App"));
const Quest = lazy(() => import("quest/App"));

<Route path="/finance/*" element={<Finance />} />
<Route path="/quest/*" element={<Quest />} />
```

## Module Federation Config

Each remote MFE exposes its root component:

```typescript
// apps/finance/rsbuild.config.ts
import { pluginModuleFederation } from "@module-federation/rsbuild-plugin";

export default {
  plugins: [
    pluginModuleFederation({
      name: "finance",
      exposes: {
        "./App": "./src/App.tsx",
      },
      shared: ["react", "react-dom", "react-router-dom"],
    }),
  ],
};
```

## Routing Convention

| Pattern | Owner |
|---------|-------|
| `/` | Shell (home/dashboard) |
| `/finance/*` | Finance MFE |
| `/quest/*` | Quest MFE |
| `/muse/*` | Muse MFE |
| `/settings/*` | Shell (global settings) |

Each MFE handles its own sub-routing internally.

## API Communication

Each MFE talks **only** to its own backend service:

```
apps/finance/  →  services/finance/  (port 8810)
apps/quest/    →  services/quest/    (port 8811)
apps/muse/     →  services/muse/     (port 8812)
```

API base URL is configured per-MFE, proxied through Gateway in production:

```
Production:  https://domain.com/api/finance/  → gateway → finance service
Development: http://localhost:8810/            → direct
```

## Shared UI Components

Common UI components live in `libs/typescript/`:

```typescript
// libs/typescript/src/components/Button.tsx
// libs/typescript/src/components/Modal.tsx
// libs/typescript/src/hooks/useAuth.ts
// libs/typescript/src/types/user.ts
```

Import in any MFE:
```typescript
import { Button } from "@workshop/ui";
import { useAuth } from "@workshop/hooks";
```

## Build & Deploy

Each MFE builds independently:
```bash
cd apps/finance && pnpm build    # → dist/ with remoteEntry.js
cd apps/shell && pnpm build      # → dist/ with index.html
```

Production: Nginx serves shell's `index.html`, which dynamically loads each MFE's `remoteEntry.js`.
