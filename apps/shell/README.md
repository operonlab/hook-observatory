# Shell (Host App)

Module Federation host — provides layout, navigation, authentication context.

## Port
3000 (dev server)

## Responsibilities
- App shell (header, sidebar, navigation)
- Auth context provider (login/logout, token management)
- Module Federation host (lazy-loads remote MFEs)
- Global theme and styling

## Development
```bash
pnpm install
pnpm dev
```

## Remote MFEs
Remote micro frontends are loaded dynamically via Module Federation:
- `/finance/*` → `@workshop/finance`
- `/quest/*` → `@workshop/quest`
- `/muse/*` → `@workshop/muse`
