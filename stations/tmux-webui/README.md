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
