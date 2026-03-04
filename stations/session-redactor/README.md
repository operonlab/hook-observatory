# Session Redactor 工作站

> 轉錄檔敏感資料清理 — SessionEnd hook 觸發，掃描 .jsonl 並移除 API key / 密碼 / token 等機密。

## 定位

Workshop `stations/` 下的獨立工作站。在 Claude Code session 結束時自動掃描轉錄檔，清除敏感資料，確保後續的 lore 記憶提煉不會接觸到原始機密。

## 在 SessionEnd Pipeline 中的位置

```
SessionEnd Hook 觸發
  │
  ├── 1️⃣  session-redactor    ← 先清敏感資料（本工具）
  │       掃描 .jsonl → 移除 API key / 密碼 / token
  │       ↓ 乾淨的轉錄檔
  ├── 2️⃣  lore extract        ← 從乾淨轉錄檔提煉記憶
  │       提煉記憶 → 建立 Galaxy
  │
  └── 3️⃣  observability       ← 記錄事件
```

**為什麼不併入 lore**：
- 單一職責：安全清理 ≠ 知識管理
- 故障隔離：redactor 壞了 → lore 照跑（寧可不清也不能阻斷記憶提煉）
- 更新節奏不同：敏感模式更新頻率 ≠ 記憶提煉邏輯更新
- 複用性：redactor 也清 `recall` (zippoxer) 等其他工具的轉錄檔

## V1 資產

| 元件 | 位置 | 說明 |
|------|------|------|
| `redact-session.sh` | V1: `~/Claude/projects/session-redactor/scripts/` | SessionEnd hook 入口（非阻塞） |
| `redactor.py` | `src/session_redactor/` | 核心清理邏輯（JSON parse + regex + atomic write） |
| `patterns.py` | `src/session_redactor/` | 16 種敏感模式定義 |
| `scanner.py` | `src/session_redactor/` | 每日 4 AM 完整掃描 |
| `db.py` | `src/session_redactor/` | SQLite 追蹤歷史 |
| SQLite DB | `~/.local/share/workshop/session_redactor.sqlite` | 清理紀錄 |

## 偵測的敏感模式（16 種）

| 類別 | 模式 |
|------|------|
| **密碼** | `echo "xxx" \| sudo -S`、中文「密碼是：xxx」、`password = "xxx"`、括號/引號變體 |
| **API Key** | Anthropic `sk-ant-*`、OpenAI `sk-*`、GitHub `ghp_*/ghs_*` |
| **Token** | Bearer token（20+ 字元） |
| **AWS** | `AKIA` 開頭 access key、`AWS_SECRET` 環境變數 |
| **SSH** | `-----BEGIN ... PRIVATE KEY-----` |
| **DB 連線** | `://user:password@host` 格式 |
| **通用** | `password/secret/token/api_key = [value]` 正規表達式 |

## 觸發機制

| 觸發方式 | 時機 | 說明 |
|---------|------|------|
| **SessionEnd Hook** | 每次 Claude Code session 結束 | 非阻塞：背景 spawn + disown，立即返回 exit 0 |
| **Daily Sweep** | 每日 4 AM | `scanner.py` 完整掃描所有 .jsonl |
| **手動** | 隨時 | 直接呼叫 Python 模組 |

## 工作流程

```
SessionEnd 事件（stdin JSON）
    ↓
redact-session.sh（背景 subprocess）
    ↓
Python redactor.redact_file()
    ├── 讀取 .jsonl（session transcript）
    ├── 逐行 JSON parse
    ├── 遞迴走訪所有字串值，套用 16 個 PATTERNS
    ├── 若有異動：atomic write（.tmp → rename）
    └── 記錄到 SQLite（追蹤清理歷史）
```

## 目錄結構（規劃）

```
stations/session-redactor/
├── README.md                  ← 本文件
├── scripts/
│   └── redact-session.sh      ← SessionEnd hook 入口
├── src/session_redactor/
│   ├── __init__.py
│   ├── redactor.py            ← 核心清理邏輯
│   ├── patterns.py            ← 16 種敏感模式
│   ├── scanner.py             ← Daily sweep
│   ├── db.py                  ← SQLite CRUD
│   └── config.py              ← 設定（掃描時間、DB 路徑等）
└── pyproject.toml
```

## 遷移計劃

1. 複製 V1 `~/Claude/projects/session-redactor/` 到 `stations/session-redactor/`
2. 更新 `~/.claude/settings.json` hook 路徑指向新位置
3. 確認 SessionEnd pipeline 順序：redactor → lore extract → observability
4. （可選）遷移 SQLite → PostgreSQL，與 Core API 整合清理統計

## 相依

- **Claude Code hooks** — SessionEnd 觸發
- **lore pipeline**（間接）— redactor 必須在 lore extract 之前執行
- **SQLite** — 清理紀錄追蹤

## 參考

- V1 位置（已遷移）：`~/Claude/projects/session-redactor/`
- Hook 設定：`~/.claude/settings.json`（SessionEnd entries）
- SQLite DB：`~/.local/share/workshop/session_redactor.sqlite`
