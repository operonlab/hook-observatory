---
source_hash: d50be69d
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# System Monitor Workstation

> Disk analysis + hardware resource pressure monitoring — evolved from V1 daily reports to a weekly system + real-time alerts.

## Positioning

An independent workstation under `stations/`, integrating the V1 disk analysis service (`~/.claude/data/disk-report/`) and expanding it with hardware resource monitoring capabilities.

## V1 Assets (Verified and Effective)

| Component | Location | Retention/Change |
|---|---|---|
| `collect-disk-data.sh` | `~/.claude/data/disk-report/` | **Retain** single scan logic, change invocation frequency |
| `generate-report.sh` | Same as above | **Retain** dual-layer intelligent routing (API → offline fallback) |
| `prompts/` | Same as above (daily/weekly/monthly) | **Adjust** remove daily, retain weekly/monthly |
| `web/` | Same as above (FastAPI + HTML5, port 9527) | **Upgrade** integrate into a Workbench Widget |
| `com.joneshong.disk-report.plist` | `~/Library/LaunchAgents/` | **Change frequency** daily → weekly |

## V2 Goals

### 1. Disk Analysis (Weekly Basis)

```
V1: Triggers daily at 05:00 UTC → Generates AI analysis report
  ↓
V2: Triggers every Monday at 05:00 UTC → Generates weekly report + monthly report (manual trigger for instant analysis available)
```

**Schedule**:
| Frequency | Time | Output |
|---|---|---|
| Weekly | Monday 05:00 UTC | Weekly disk report (space change, trend, cleanup suggestions) |
| Monthly | 1st of each month | Monthly trend report (long-term space growth curve) |
| Manual | Anytime | Instant scan (triggered by API or CLI) |

### 2. Hardware Resource Monitoring (New)

V1 only had disk analysis; V2 expands to comprehensive hardware monitoring:

| Monitored Item | Collection Method | Alert Threshold |
|---|---|---|
| **CPU** | `top -l 1` / `sysctl` | 5-minute average > 80% |
| **Memory** | `vm_stat` / `memory_pressure` | pressure level = critical |
| **Disk** | `df` / `du` (V1 collection script) | Usage > 85% |
| **Swap** | `sysctl vm.swapusage` | Swap usage > 2GB |
| **Temperature** | `sudo powermetrics` (Apple Silicon) | > 95°C |
| **Battery** | `pmset -g batt` (for MacBooks) | < 20% |

**Pressure Levels**:
```
🟢 normal  — Everything is normal
🟡 warning — Nearing threshold (logged but no alert)
🔴 critical — Exceeded threshold (notify Master)
⚫ danger  — Severe pressure (automatic cleanup suggestions)
```

### 3. Report Format

```json
{
  "timestamp": "2026-02-24T05:00:00Z",
  "type": "weekly",
  "disk": {
    "total_gb": 500,
    "used_gb": 380,
    "usage_pct": 76,
    "top_consumers": [...],
    "weekly_delta_gb": +2.3,
    "ai_analysis": "Disk usage is growing steadily..."
  },
  "hardware": {
    "cpu_avg_5m": 23.5,
    "memory_pressure": "normal",
    "memory_used_gb": 12.8,
    "swap_used_gb": 0.1,
    "temperature_c": 52
  },
  "pressure_level": "normal",
  "recommendations": [...]
}
```

## API Endpoints (`/api/stations/system-monitor/`)

| Method | Path | Description |
|---|---|---|
| GET | `/reports` | List of historical reports (supports type filtering, pagination) |
| GET | `/reports/latest` | The latest report |
| GET | `/reports/:id` | Details of a single report |
| POST | `/scan` | Manually trigger an instant scan |
| GET | `/status` | Real-time hardware status (lightweight, without AI analysis) |
| GET | `/trends` | Trend data (disk growth curve, CPU/RAM history) |
| GET | `/alerts` | Alert history |

## Workbench Widget

A card on the Dashboard homepage for an at-a-glance view of system health:

```
┌─── System Monitor ──────────────────────┐
│                                         │
│  💾 Disk: 380/500 GB (76%)  🟢         │
│  🧠 RAM:  12.8/32 GB       🟢         │
│  ⚡ CPU:  23% avg           🟢         │
│  🌡️  Temp: 52°C            🟢         │
│                                         │
│  Last scan: 2026-02-24 (Weekly)         │
│  Trend: +2.3 GB/week                   │
│  [View Full Report →]                   │
└─────────────────────────────────────────┘
```

## Directory Structure

```
stations/system-monitor/
├── README.md              ← This document
├── collect.sh             ← Data collection script (inherits from V1 collect-disk-data.sh)
├── hardware.sh            ← Hardware resource collection script (new)
├── generate-report.sh     ← Report generation (inherits from V1, dual-layer LLM routing)
├── prompts/
│   ├── weekly.md          ← Weekly report prompt
│   └── monthly.md         ← Monthly report prompt
├── config.json            ← Schedule configuration, thresholds, notification settings
└── web/                   ← Workbench Widget data endpoint (or provided directly by Core API)
```

## Migration Plan

1.  Copy V1 core scripts to `stations/system-monitor/`
2.  Adjust launchd plist frequency (daily → weekly)
3.  Add new `hardware.sh` script for hardware collection
4.  Create Core API endpoints (`/api/stations/system-monitor/`)
5.  Create Workbench Widget (system health card)
6.  Set up alert notification channel (notification bridge)

## Dependencies

-   **station-sdk** (`libs/sdk-client/`) — Schedule management, Core API push, Widget data format, notification integration (see [AD-8](../../docs/architecture/architecture-decisions.md#ad-8-station-sdk--工作站共享層))
-   **Core API** (optional) — For persisting reports to DB + Workbench Widget
-   **notification bridge** (optional) — For alert push notifications
-   V1 launchd scheduling infrastructure

## References

-   V1 Disk Analysis: `~/.claude/data/disk-report/`
-   V1 Schedule: `~/Library/LaunchAgents/com.joneshong.disk-report.plist`
-   V1 Web UI: port 9527
-   Report Output: `~/workshop/outputs/disk-report/`
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2703ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2748ms
