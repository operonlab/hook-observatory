# tmux Web UI 工作站

> 瀏覽器控制 tmux — 多面板即時控制、系統指標顯示、LLM 用量一覽。

## 定位

Workshop `stations/` 下的獨立工作站。提供 Web 介面管理 tmux sessions/windows/panes，同時顯示系統指標（CPU、RAM、Disk、Network）與 LLM 用量。

## V1 資產

| 元件 | 位置 | 說明 |
|------|------|------|
| `server.py` | `~/Claude/projects/tmux-webui/` | 單檔 Python，aiohttp，75KB |
| tmux 狀態腳本 | `~/.tmux/scripts/` | net-speed, cpu-status, mem-status, disk-status |
| sysmon 資料 | `/tmp/pulso-sysmon-latest.json` | LLM 用量 fallback |

## 功能

| 功能 | 說明 |
|------|------|
| **Session 瀏覽** | 列出所有 tmux sessions + windows + panes |
| **Pane 控制** | 從瀏覽器向 tmux pane 發送指令 |
| **多面板檢視** | 同時監看多個 pane 的輸出 |
| **系統指標** | CPU / RAM / Disk / Network 即時狀態 |
| **LLM 用量** | Claude 5h/7d、Codex 5h/7d、Gemini Pro 用量 |

## V2 升級計畫（P3-E）

> 參考 **Blink Shell** 和 **iSH** 的手機 SSH 操作體驗，打造觸控友善的 Web Terminal。

### 虛擬按鍵列（Virtual Key Bar）

螢幕底部常駐快捷鍵列，手機開發必備：

| 類別 | 按鍵 | 用途 |
|------|------|------|
| 導航 | `←` `→` `↑` `↓` | 方向鍵（命令歷史、游標移動） |
| 控制 | `Tab` `Esc` `Ctrl` `Alt` | 自動補全、取消、組合鍵 |
| 開發常用 | `\|` `/` `-` `_` `~` `.` | Pipe、路徑、flag |
| 組合 | `Ctrl+C` `Ctrl+D` `Ctrl+Z` `Ctrl+L` | 中斷、EOF、暫停、清屏 |

**Ctrl 模式**：點擊 Ctrl → 高亮 → 點擊字母 → 送出 Ctrl+字母 → 自動退出。

### 命令自動補全（Autocomplete）

- **命令歷史**：tmux scrollback buffer 或 shell history
- **路徑補全**：server 端 `os.listdir()` + glob match
- **常用指令**：預設 + 使用者自訂清單
- **tmux 指令**：`tmux ls`、`tmux split-window` 等

### 觸控手勢

| 手勢 | 動作 |
|------|------|
| 左右滑動 | 切換 tmux pane |
| 雙指縮放 | 調整字體大小 |
| 長按選取 | 複製文字 |
| 底部上滑 | 展開/收合虛擬鍵盤 |

### UI/UX 強化

- **響應式佈局**：桌面多面板並排；手機單面板 + 滑動切換
- **連線狀態**：斷線自動重連 + 視覺回饋
- **字體調整**：可調整終端字體大小
- **Pane 快速切換**：底部 tab bar 或側邊抽屜

詳見 [P3-E 完整規劃](../../docs/blueprint/p3-stations.md)

## 啟動

```bash
uv run ~/Claude/projects/tmux-webui/server.py              # port 8765
uv run ~/Claude/projects/tmux-webui/server.py --port 3000   # custom port
```

## 技術

- **語言**：Python 3.12
- **框架**：aiohttp（單檔，inline script dependencies）
- **依賴**：`aiohttp`（唯一外部依賴）
- **前端**：內嵌 HTML/CSS/JS（server.py 內）
- **預設 Port**：8765

## 目錄結構（規劃）

```
stations/tmux-webui/
├── README.md          ← 本文件
└── server.py          ← 主程式（從 V1 遷入）
```

## 遷移計劃

1. 複製 `server.py` 到 `stations/tmux-webui/`
2. 更新啟動指令路徑
3. （可選）與 llm-usage station 整合 LLM 用量資料來源

## 相依

- **tmux** — 必須在本機安裝
- **tmux 狀態腳本**（`~/.tmux/scripts/`）— 系統指標顯示
- **sysmon**（可選）— LLM 用量 fallback

## 參考

- V1 位置：`~/Claude/projects/tmux-webui/`
