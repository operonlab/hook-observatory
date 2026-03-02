# tmux Web UI V2

> 瀏覽器控制 tmux — 多面板即時控制、觸控友善、系統指標 + LLM 用量一覽。

## 定位

Workshop `stations/` 下的獨立工作站。提供 Web 介面管理 tmux sessions/windows/panes，同時顯示系統指標（CPU、RAM、Disk、Network）與 LLM 用量。參考 Blink Shell / iSH 的觸控友善操作體驗。

## 功能

| 功能 | 說明 |
|------|------|
| **Session 瀏覽** | 列出所有 tmux sessions + windows + panes |
| **Pane 控制** | 從瀏覽器向 tmux pane 發送指令 |
| **多面板檢視** | 同時監看多個 pane 的輸出（桌面並排） |
| **ANSI 渲染** | 完整 SGR 支援：16/256/TrueColor 色彩 |
| **虛擬按鍵列** | Ctrl/Alt/Cmd + Tab/Esc + `/.:;|-_~` + Ctrl+C/D/Z/L + 方向鍵 |
| **觸控手勢** | 左右滑動切 pane、雙指縮放字體、長按選取、底部上滑展開鍵盤 |
| **路徑補全** | Server 端 `os.listdir()` + glob 即時補全 |
| **指令補全** | 從 `~/.zsh_history` 搜尋歷史指令 |
| **Skill 補全** | 掃描 `~/.claude/skills/` 補全 skill 名稱 |
| **Tool Profiles** | 偵測 Claude/Codex/Gemini/Aider/Cursor 顯示快捷按鈕 |
| **Skill Palette** | 分類展開、搜尋過濾所有 Claude Code skills |
| **系統指標** | CPU / RAM / Disk / Network 即時狀態列 |
| **LLM 用量** | Claude 5h/7d/EX、Codex 5h/7d、Gemini Pro |
| **響應式佈局** | 桌面多面板並排；手機單面板 + 底部 tab bar 切換 |
| **斷線重連** | Exponential backoff（1s→2s→4s→...→30s）+ 狀態指示 |
| **PWA** | 可安裝為手機主畫面 App |

## 啟動

```bash
cd ~/workshop/stations/tmux-webui
uv run server.py                    # port 9527 (預設)
uv run server.py --port 3000        # 自訂 port
```

## 設定

`config.json`（與 server.py 同目錄）：

```json
{
  "host": "127.0.0.1",
  "port": 9527,
  "poll_interval": 0.4,
  "metrics_interval": 5.0,
  "capture_lines": 150,
  "theme": "catppuccin-mocha"
}
```

## 目錄結構

```
stations/tmux-webui/
├── server.py           ← FastAPI 主程式 + WebSocket + HTTP routes
├── tmux_manager.py     ← tmux 操作封裝
├── autocomplete.py     ← 路徑 + 指令歷史 + skill 補全引擎
├── config.py           ← 設定管理
├── config.json         ← 預設設定
├── templates/
│   └── index.html      ← Jinja2 主模板
├── static/
│   ├── css/
│   │   └── main.css    ← Catppuccin 深色主題
│   ├── js/
│   │   ├── app.js      ← 主應用邏輯（狀態、佈局、WebSocket、Tool Profiles）
│   │   ├── terminal.js ← ANSI-to-HTML 解析器
│   │   ├── keys.js     ← 虛擬按鍵 + Ctrl 組合鍵
│   │   ├── autocomplete.js ← 前端補全 UI
│   │   ├── gestures.js ← 觸控手勢處理
│   │   └── metrics.js  ← 系統指標 + LLM 用量渲染
│   └── icons/
│       ├── icon-192.svg
│       └── icon-512.svg
└── README.md
```

## 技術

- **語言**：Python 3.12
- **後端**：FastAPI + uvicorn + Jinja2 + websockets
- **前端**：Vanilla JS（模組分離，無框架）
- **主題**：Catppuccin Mocha

## 相依

- **tmux** — 必須在本機安裝
- **tmux 狀態腳本**（`~/.tmux/scripts/`）— 系統指標
- **sysmon**（可選）— LLM 用量 fallback
