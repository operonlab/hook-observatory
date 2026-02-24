# System Monitor 工作站

> 磁碟分析 + 硬體資源壓力監控 — 從 V1 每日報告演進為週報制 + 即時警報。

## 定位

Workshop `stations/` 下的獨立工作站，整合 V1 磁碟分析服務（`~/.claude/data/disk-report/`）並擴充硬體資源監控能力。

## V1 資產（已驗證有效）

| 元件 | 位置 | 保留/改動 |
|------|------|----------|
| `collect-disk-data.sh` | `~/.claude/data/disk-report/` | **保留** 單次掃描邏輯，改調用頻率 |
| `generate-report.sh` | 同上 | **保留** 雙層智能路由（API → 離線 fallback） |
| `prompts/` | 同上（daily/weekly/monthly） | **調整** 移除 daily，保留 weekly/monthly |
| `web/` | 同上（FastAPI + HTML5, port 9527） | **升級** 整合到 Workbench Widget |
| `com.joneshong.disk-report.plist` | `~/Library/LaunchAgents/` | **改頻率** 每日 → 每週 |

## V2 目標

### 1. 磁碟分析（週報制）

```
V1：每日 05:00 UTC 觸發 → 生成 AI 分析報告
  ↓
V2：每週一 05:00 UTC 觸發 → 生成週報 + 月報（可手動觸發即時分析）
```

**排程**：
| 頻率 | 時間 | 產出 |
|------|------|------|
| 每週 | 週一 05:00 UTC | 磁碟週報（空間變化、趨勢、清理建議） |
| 每月 | 每月 1 日 | 月度趨勢報告（長期空間增長曲線） |
| 手動 | 隨時 | 即時掃描（API 或 CLI 觸發） |

### 2. 硬體資源監控（新增）

V1 只有磁碟分析，V2 擴充為全方位硬體監控：

| 監控項目 | 採集方式 | 警報門檻 |
|---------|---------|---------|
| **CPU** | `top -l 1` / `sysctl` | 5 分鐘平均 > 80% |
| **Memory** | `vm_stat` / `memory_pressure` | pressure level = critical |
| **Disk** | `df` / `du`（V1 收集腳本） | 使用率 > 85% |
| **Swap** | `sysctl vm.swapusage` | swap 使用 > 2GB |
| **Temperature** | `sudo powermetrics`（Apple Silicon） | > 95°C |
| **Battery** | `pmset -g batt`（MacBook 時） | < 20% |

**壓力等級**：
```
🟢 normal  — 一切正常
🟡 warning — 接近門檻（記錄但不警報）
🔴 critical — 超過門檻（通知少爺）
⚫ danger  — 嚴重壓力（自動清理建議）
```

### 3. 報告格式

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
    "ai_analysis": "磁碟使用量穩定增長..."
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

## API 端點（`/api/stations/system-monitor/`）

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/reports` | 歷史報告列表（支援 type 過濾、分頁） |
| GET | `/reports/latest` | 最新一份報告 |
| GET | `/reports/:id` | 單筆報告詳情 |
| POST | `/scan` | 手動觸發即時掃描 |
| GET | `/status` | 即時硬體狀態（輕量級，不含 AI 分析） |
| GET | `/trends` | 趨勢資料（磁碟增長曲線、CPU/RAM 歷史） |
| GET | `/alerts` | 警報歷史 |

## Workbench Widget

Dashboard 首頁卡片，一眼看到系統健康狀態：

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

## 目錄結構

```
stations/system-monitor/
├── README.md              ← 本文件
├── collect.sh             ← 資料收集腳本（承接 V1 collect-disk-data.sh）
├── hardware.sh            ← 硬體資源採集腳本（新增）
├── generate-report.sh     ← 報告生成（承接 V1，雙層 LLM 路由）
├── prompts/
│   ├── weekly.md          ← 週報提示詞
│   └── monthly.md         ← 月報提示詞
├── config.json            ← 排程配置、門檻值、通知設定
└── web/                   ← Workbench Widget 資料端點（或直接由 Core API 提供）
```

## 遷移計劃

1. 複製 V1 核心腳本到 `stations/system-monitor/`
2. 調整 launchd plist 頻率（daily → weekly）
3. 新增 `hardware.sh` 硬體採集腳本
4. 建立 Core API 端點（`/api/stations/system-monitor/`）
5. 建立 Workbench Widget（系統健康卡片）
6. 設定警報通知管道（notification bridge）

## 相依

- **station-sdk**（`libs/python/station-sdk/`）— 排程管理、Core API 推送、Widget 資料格式、通知整合（參見 [AD-8](../../docs/architecture/architecture-decisions.md#ad-8-station-sdk--工作站共享層)）
- **Core API**（可選）— 若要持久化報告到 DB + Workbench Widget
- **notification bridge**（可選）— 警報推送
- V1 launchd 排程基礎設施

## 參考

- V1 磁碟分析：`~/.claude/data/disk-report/`
- V1 排程：`~/Library/LaunchAgents/com.joneshong.disk-report.plist`
- V1 Web UI：port 9527
- 報告輸出：`~/Claude/disk-report/`
