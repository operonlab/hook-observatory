# New Module Onboarding Checklist

When adding a new frontend module or station, complete ALL applicable items before considering the task done.

## Core Module (runs inside core on port 10000)

Examples: briefing, finance, memvault, intelflow, notification

| # | Item | File |
|---|------|------|
| 1 | RBAC permissions | `core/src/modules/auth/permissions.py` → `ROLE_PERMISSIONS` (user + guest) |
| 2 | App Launcher entry | `workbench/src/shared/constants/apps.ts` |
| 2 | Sentinel light check (HTTP) | `stations/sentinel/checker.py` → `LIGHT_CHECKS` |
| 3 | Sentinel deep check (Playwright) | `stations/sentinel/checker.py` → `DEEP_CHECKS` + `_short_names` |
| 4 | Frontend build | `pnpm run build` in `workbench/` |

No separate service entry needed — core already managed by `scripts/workshop_services.py`.

## Standalone Station (own port, own process)

Examples: agent-metrics, hook-observatory, auto-survey, system-monitor

All of the above, plus:

| # | Item | File |
|---|------|------|
| 5 | Port registry | `libs/sdk-client/sdk_client/port_registry.py` → `PORTS` |
| 6 | Service registry | `scripts/workshop_services.py` → `SERVICES` |
| 7 | Sentinel remediation map | `stations/sentinel/remediation.py` → `SIMPLE_RESTART_MAP` |
| 8 | Nginx reverse proxy | `/opt/homebrew/etc/nginx/conf.d/workshop-apps.inc` |

## Reference: Existing Patterns

- **App Launcher entry**: Copy structure from `apps.ts`, set `status: 'available'` for internal routes, `status: 'external'` + `externalUrl` for station UIs
- **Sentinel light check**: Core modules use `group="internal"`, `expect_contains='<div id="root">'`; stations use `group="external"`
- **Sentinel deep check**: Core modules use `_PW_ROOT_CHECK`; stations use `_PW_BODY_CHECK`
- **Nginx proxy**: Include `auth_request /_v2_auth_check` + `error_page 401 = @auth_redirect` for authenticated access
