---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

> [← 返回優先藍圖總覽](./v2-priorities.md)

# P3：Station 整合 — 系統監控 + LLM 用量 + 環境工具 + 情報主題管理 + tmux-webui

### 概述

將散落的 V1 工具整合到 Workshop `stations/` 目錄下，並為 intelflow 模組新增 Daily Briefing 動態主題管理。

### P3-A：System Monitor — 磁碟 + 硬體監控

**現況**：V1 磁碟分析運作良好（`~/.claude/data/disk-report/`，每日 launchd 排程）。

**V2 變更**：
- 頻率調整：每日 → 每週（週一 05:00 UTC）+ 月報
- 新增硬體資源監控：CPU / RAM / Swap / 溫度 / 電池
- 壓力等級判定 + 警報通知
- Workbench Widget（系統健康卡片）
- Core API 端點（`/api/stations/system-monitor/`）

**技術架構**：
```
stations/system-monitor/
├── collect.sh           ← 磁碟 + 硬體資料收集
├── generate-report.sh   ← AI 分析報告（雙層 LLM 路由）
└── config.json          ← 排程、門檻值、通知設定
      ↓
workbench Widget ← Core API ← 報告 DB / 即時狀態
```

### P3-B：LLM Usage — 雙軌用量追蹤

**現況**：LLM 用量分散在兩個世界 — 會員制 CLI 工具（CC/Codex/Gemini）的用量比率 + 另外購買的 API 服務（LiteLLM），無法統一回答「這個月總共用了多少？」

**V2 變更**：
- **會員制追蹤**：各 CLI 工具的方案月費 + 用量額度消耗比率
- **API 追蹤**：LiteLLM DB 同步 → token 數 + 實際金額（Agent SDK 等場景）
- 雙軌分析：會員制（固定月費 + 額度）vs API（按量計費）
- API 預算追蹤 + Cache 效率統計
- model-policy 改讀統一 DB
- Workbench Widget（雙軌成本儀表板）

**技術架構**：
```
── 會員制（Subscription）───────────────
CC / Codex / Gemini CLI → hooks + logs → subscription.py → DB

── API（Pay-per-use）───────────────────
Agent SDK / 自建服務 → LiteLLM Proxy → api_collector.py → DB

                                    ↓
                 workbench Widget ← Core API
```

### P3-C：EnvKit — 完整環境管理（取代 ~/dotfiles/）

**現況**：`~/dotfiles/` 有安裝清單但缺分類、缺設定備份、缺還原順序。少爺說「不是我要的」。

**V2 重新設計（取代 dotfiles，非互補）**：
- 5 層環境清冊：Tier 1 核心設定（tmux/zsh/CC）→ Tier 2 重要工具 → Tier 3 CLI → Tier 4 服務 → Tier 5 GUI
- Config 備份：檔案複製 + 匯出還原 + git 追蹤 + 雲端同步，四種策略
- 9 階段 Bootstrap Pipeline（依賴順序安裝 + 設定還原）
- `envkit snapshot/backup/bootstrap/verify/diff` CLI
- 穩定後歸檔 `~/dotfiles/`

### P3-D：Daily Briefing 主題管理（intelflow 模組擴充）

**現況**：V1 的 6 個情報主題完全寫死在 `run.sh`（530 行 shell 腳本）。

**V2 變更**：
- DB 表：`intelflow.briefing_topics` + `intelflow.briefing_subtopics`
- 動態 CRUD：可新增/修改/啟停主題 + 子分類
- 子分類參數化：例如天氣→輸入在意的地區（台北、東京、紐約）
- 主題管理 UI：`/intelflow/briefings/settings`（樹狀結構，可勾選啟停）
- 三分析師管線保留：改為讀取動態主題設定
- V1 → V2 遷移：首次啟動自動建立 6 個預設主題

### P3-E：tmux-webui — 手機 SSH 體驗升級

**現況**：V1 功能完整（session 瀏覽、pane 控制、系統指標），體驗不錯，可以此為基底修改。

**痛點**：
- Input 沒有任何 autocomplete 提示
- 缺少手機觸控友善的虛擬按鍵
- 未發揮 Web 平台的 UI/UX 優勢

**V2 目標**：參考 **Blink Shell** 和 **iSH** 等手機 SSH App 的操作體驗，打造觸控友善的 Web Terminal。

#### 1. 虛擬按鍵列（Virtual Key Bar）

參考 Blink Shell 的設計：

```
┌──────────────────────────────────────────────────────┐
│  Terminal Output Area                                 │
│  $ ls -la                                            │
│  drwxr-xr-x  10 user  staff  320 Feb 24 13:00 .     │
│                                                      │
├──────────────────────────────────────────────────────┤
│  [Tab] [Esc] [Ctrl] [Alt] [←] [→] [↑] [↓] [|] [/]  │  ← 常駐快捷鍵列
├──────────────────────────────────────────────────────┤
│  [input field with autocomplete dropdown]             │  ← 輸入區
└──────────────────────────────────────────────────────┘
```

**按鍵設計**：
| 類別 | 按鍵 | 用途 |
|------|------|------|
| 導航 | `←` `→` `↑` `↓` | 方向鍵（命令歷史、游標移動） |
| 控制 | `Tab` `Esc` `Ctrl` `Alt` | 自動補全、取消、組合鍵 |
| 開發常用 | `\|` `/` `-` `_` `~` `.` | Pipe、路徑、flag |
| 組合 | `Ctrl+C` `Ctrl+D` `Ctrl+Z` `Ctrl+L` | 中斷、EOF、暫停、清屏 |

**Ctrl 組合鍵模式**：點擊 `Ctrl` → 進入 Ctrl 模式（高亮）→ 點擊字母 → 送出 `Ctrl+字母` → 自動退出模式。

#### 2. 命令自動補全（Command Autocomplete）

```
輸入 "gi" → 下拉建議：
  ┌──────────────┐
  │ git           │  ← 指令補全
  │ git status    │  ← 常用組合
  │ git commit    │
  │ git push      │
  └──────────────┘

輸入 "cd ~/w" → 下拉建議：
  ┌──────────────┐
  │ ~/workshop/   │  ← 路徑補全
  │ ~/workbench/  │
  └──────────────┘
```

**補全來源**：
- **命令歷史**：從 tmux pane 的 scrollback buffer 或 shell history 擷取
- **路徑補全**：server 端 `os.listdir()` + glob match
- **常用指令**：預設 + 使用者自訂的常用指令清單
- **tmux 指令**：`tmux ls`、`tmux split-window` 等

#### 3. 觸控手勢

| 手勢 | 動作 |
|------|------|
| 左右滑動 | 切換 tmux pane |
| 雙指縮放 | 調整字體大小 |
| 長按選取 | 複製文字 |
| 從底部上滑 | 展開/收合虛擬鍵盤 |

#### 4. UI/UX 強化

- **響應式佈局**：桌面 → 多面板並排；手機 → 單面板全螢幕 + 滑動切換
- **主題**：沿用 V1 深色主題，增加字體大小調整
- **連線狀態指示**：斷線自動重連 + 視覺回饋
- **Pane 快速切換**：底部 tab bar 或側邊抽屜

### P3 遷移策略

```
P3-A (system-monitor): 複製 V1 腳本 → 改頻率 → 加硬體監控 → API + Widget
P3-B (agent-metrics):  整理會員方案 + 解析 LiteLLM DB → 雙軌收集 → API + Widget（已整合 llm-usage）
P3-C (envkit):         掃描 Mac Mini → inventory.yaml + config 備份 → bootstrap pipeline → 歸檔 ~/dotfiles/
P3-D (briefing 管理):  建立 DB 表 → 遷移寫死主題 → CRUD API → 管理 UI
P3-E (tmux-webui):     V1 為基底 → 虛擬按鍵列 → Autocomplete → 觸控手勢 → 響應式
```

### 相關文件

| 文件 | 用途 |
|------|------|
| [v2-priorities.md](./v2-priorities.md) | 藍圖索引 |
| [shared-layer-patterns.md](../architecture/shared-layer-patterns.md) | 共享層模式（DashboardWidget §9.5） |

---

**下一步** → [P4：Auth 基礎建設](./p4-auth.md)
