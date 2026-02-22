# Pulso Web

Single React application with domain modules.

## Run
pnpm install && pnpm dev

## Structure
- src/shell/ — App shell (layout, navigation, auth)
- src/modules/ — Domain modules (lazy-loaded)
- src/plugins/ — Plugin UI runtime
- src/shared/ — Shared components and constants
- src/stores/ — Global state (Zustand)
- src/api/ — API client
