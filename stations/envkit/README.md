# EnvKit 工作站

> 完整環境管理 — 取代 ~/dotfiles/，記錄所有安裝的應用程式、工具、設定，一鍵還原到新硬體。

## 定位

Workshop `stations/` 下的獨立工作站。**取代** `~/dotfiles/`，成為環境管理的唯一 source of truth。

EnvKit 的三個核心任務：
1. **快照** — 掃描 Mac Mini 上所有已安裝的 app、CLI、lib、系統設定
2. **設定備份** — 備份所有重要工具的設定檔（tmux, zsh, Claude Code 等）
3. **一鍵還原** — 新硬體跑一個腳本，還原到完全相同的工作狀態

## V1 資產（~/dotfiles/ → 即將被取代）

`~/dotfiles/` 有安裝清單 + 基礎 bootstrap，但少爺認為「不是我要的」：

| 有的 | 缺的 |
|------|------|
| brew formulae/casks 清單 | 沒有分類（哪些是網路工具、哪些是開發工具） |
| npm/uv/pip 清單 | 沒有完整的 GUI 應用清單 |
| 部分 config（tmux, zsh） | 缺少 Claude Code、iTerm2、Logi Options+ 等設定 |
| 基礎 bootstrap 腳本 | 沒有安裝順序管理、驗證、diff |

**遷移計劃**：EnvKit 穩定後，`~/dotfiles/` 歸檔停用。

---

## 環境清冊（2026-02-24 實際掃描）

### Tier 1 — 核心設定（config 必須備份）

這些工具的**設定檔**是最重要的資產，遺失等於要重頭調校：

| 工具 | 用途 | Config 位置 | 備份策略 |
|------|------|-----------|---------|
| **Claude Code** | 主力 AI CLI | `~/.claude/` | 已有 git repo（55+ 檔案：agents, rules, hooks, skills, settings） |
| **tmux** | 多工終端 | `~/.tmux.conf` + `~/.tmux/` (tpm plugins) | envkit 檔案備份 |
| **Oh My Zsh** | Shell 環境 | `~/.zshrc`, `~/.zshenv`, `~/.oh-my-zsh/custom/` | envkit 檔案備份 |

### Tier 2 — 重要工具（安裝 + config 需備份）

| 工具 | 用途 | 安裝方式 | Config 位置 |
|------|------|---------|-----------|
| **iTerm2** | 主力終端 | `brew install --cask iterm2` | Profile JSON 匯出 |
| **VS Code** | 程式碼編輯器 | `/Applications/` (手動安裝) | settings.json + extensions 清單 |
| **Tailscale** | 遠端存取 VPN | Mac App Store (`mas install 1475387142`) | 登入即還原 |
| **LuLu** | 防火牆 | `brew install --cask lulu` | 防火牆規則 |
| **OrbStack** | Docker 容器 | `brew install --cask orbstack` | `~/.orbstack/` |
| **Logi Options+** | 滑鼠/鍵盤設定 | `/Applications/` (官網安裝) | `~/Library/Application Support/LogiOptionsPlus/` |
| **Chrome** | 瀏覽器 | `/Applications/` (官網安裝) | Google 帳號登入同步 |

### Tier 3 — CLI 工具鏈

**AI 工具**：

| 工具 | 用途說明 | 安裝方式 | 狀態 |
|------|---------|---------|------|
| **Gemini CLI** | Google 的 AI CLI，跟 Claude Code 類似但用 Gemini 模型。三腦策略的執行者之一 | `brew install gemini-cli` | 活躍使用 |
| **Codex CLI** | OpenAI 的 AI CLI，三腦策略的執行者之一。擅長確定性小任務 | `brew install --cask codex` | 活躍使用 |
| **Ollama** | 本地跑 LLM / Embedding 模型。目前跑 nomic-embed-text (KAS 向量化) + qwen2.5:0.5b (輕量測試) | `brew install ollama` | 活躍使用 |
| **LiteLLM** | 統一 LLM API Proxy，多 Provider 路由。用於 Agent SDK 等自建 Agent 場景的 API 服務 | `uv tool install litellm` | 活躍使用 |
| **mlx-lm** | Apple Silicon 優化的本地 LLM 推理框架。跑 MLX 格式模型（如 Qwen3-TTS） | `uv tool install mlx-lm` | 偶爾實驗 |
| **edge-tts** | Microsoft Edge 的免費 TTS 引擎。用於 Claude Code session 語音播報通知 | `uv tool install edge-tts` | 活躍使用 |
| **Claude Squad** | TUI 多 agent 管理器。同時管理多個 Claude Code instance，視覺化狀態 | `brew install claude-squad` | 活躍使用 |
| **Recall** | Claude Code session 歷史全文搜尋 TUI。搜尋過去對話找回遺忘的細節 | `brew install recall` | 活躍使用 |
| **summarize** | 網頁/連結→純文字→摘要。快速把 URL 轉成乾淨文字 | `brew install steipete/tap/summarize` | 偶爾使用 |
| **remindctl** | Apple Reminders CLI。從終端機快速建立/查看提醒事項 | `brew install steipete/tap/remindctl` | 偶爾使用 |

**開發工具**：

| 工具 | 用途說明 | 安裝方式 | 狀態 |
|------|---------|---------|------|
| **uv** | Rust 寫的超快 Python 套件管理器。管理 Python 3.12 + 虛擬環境 + 工具安裝 | `brew install uv` | 核心工具 |
| **bun** | 超快 JS runtime + bundler + 套件管理。部分專案用 bun 取代 node | `brew install bun` | 活躍使用 |
| **Node.js** | JS runtime。node@22 是 LTS 版本 | `brew install node` + `node@22` | 核心工具 |
| **pnpm** | 快速節省空間的 Node 套件管理器。Workshop 前端用 pnpm | `npm install -g pnpm` | 核心工具 |
| **Go** | Go 語言。部分社群工具 (claude-squad, recall) 的依賴 | `brew install go` | 間接依賴 |
| **gh** | GitHub CLI。建立 PR、查看 Issue、管理 repo 等 | `brew install gh` | 活躍使用 |
| **git-lfs** | Git 大檔案追蹤。用於版控大型二進位檔案 | `brew install git-lfs` | 偶爾需要 |

**搜尋/文字處理**：

| 工具 | 用途說明 | 安裝方式 | 狀態 |
|------|---------|---------|------|
| **ripgrep** | 超快的正則搜尋（比 grep 快 10x+）。Claude Code 底層也用它 | `brew install ripgrep` | 核心工具 |
| **fzf** | 模糊搜尋。Ctrl+R 歷史搜尋、檔案搜尋等互動式過濾器 | `brew install fzf` | 核心工具 |
| **bat** | cat 的替代品，帶語法高亮 + 行號 + Git 整合 | `brew install bat` | 活躍使用 |
| **fd** | find 的替代品，更快更直覺的語法 | `brew install fd` | 活躍使用 |
| **zoxide** | cd 的智慧替代品，記住常去目錄，打 `z foo` 直接跳轉 | `brew install zoxide` | 活躍使用 |
| **pandoc** | 萬用文件格式轉換器。Markdown↔HTML↔PDF↔DOCX 等 | `brew install pandoc` | 偶爾使用 |
| **tesseract** | 開源 OCR 引擎。圖片文字辨識，tesseract-lang 提供多語言支援 | `brew install tesseract` + `tesseract-lang` | 偶爾使用 |

**網路/系統**：

| 工具 | 用途說明 | 安裝方式 | 狀態 |
|------|---------|---------|------|
| **mosh** | SSH 的替代品，斷線自動重連 + 低延遲。遠端連線更穩定 | `brew install mosh` | 偶爾使用 |
| **cloudflared** | Cloudflare Tunnel 客戶端。把本地服務安全暴露到外網（不用開 port） | `brew install cloudflared` | 偶爾使用 |
| **ttyd** | 把終端機分享到瀏覽器。tmux-webui 的底層元件之一 | `brew install ttyd` | 活躍使用 |
| **mc** | Midnight Commander，終端機雙欄檔案管理器。快速瀏覽/搬移檔案 | `brew install mc` | 偶爾使用 |
| **lynis** | 系統安全審計工具。掃描 macOS 安全設定並給建議 | `brew install lynis` | 偶爾審計 |
| **gnupg** | GPG 加密/簽章工具。Git commit 簽名、檔案加密 | `brew install gnupg` | 偶爾需要 |
| **ffmpeg** | 萬用媒體處理。影片轉檔、切割、合併、音訊處理等 | `brew install ffmpeg` | 活躍使用 |
| **mlx** | Apple Silicon 原生 ML 框架（C++ 底層）。mlx-lm 的底層依賴 | `brew install mlx` | 間接依賴 |

**npm 全域套件**：

| 套件 | 用途說明 | 狀態 |
|------|---------|------|
| **@google/clasp** | Google Apps Script CLI。從終端機部署/管理 Google Apps Script 專案 | 偶爾使用 |
| **docx** | Node.js Word 文件生成。用於 docx skill 產生 .docx 報告 | 活躍使用 |
| **pptxgenjs** | Node.js PowerPoint 生成。用於 pptx skill 產生 .pptx 簡報 | 活躍使用 |


### Tier 4 — Docker 服務（OrbStack）

所有後端服務透過 OrbStack 容器運行，不直接安裝在 macOS：

| 容器 | 映像檔 | 用途 |
|------|--------|------|
| **pulso-postgres** | `postgres:16-alpine` | 主資料庫 |
| **pulso-redis** | `redis:7-alpine` | Cache + Event Bus |
| **pulso-lgtm** | `grafana/otel-lgtm:latest` | Observability (Grafana + LGTM) |
| **rustfs** | `rustfs/rustfs:latest` | 物件儲存 (S3-compatible) |

備份策略：`docker-compose.yml` + volume 備份

### Tier 5 — 其他 GUI 應用

| 應用 | 用途說明 | 安裝方式 | 狀態 |
|------|---------|---------|------|
| **Zed** | Rust 寫的高效能編輯器。VS Code 的輕量替代品，啟動快 | `brew install --cask zed` | 偶爾使用 |
| **LibreOffice** | 免費辦公套件。開啟/編輯 Office 格式檔案 | `brew install --cask libreoffice` | 偶爾使用 |
| **KnockKnock** | Objective-See 出品的安全工具。掃描 macOS 上所有持久化元件（啟動項目、kernel extensions 等） | `brew install --cask knockknock` | 偶爾審計 |
| **CC Switch** | Claude Code 多帳號切換工具。在不同 Anthropic 帳號間快速切換 | `brew install --cask cc-switch` | 活躍使用 |
| **LINE** | 通訊軟體。日常聯繫 + 未來 LINE Bot Bridge | Mac App Store | 活躍使用 |
| **Telegram** | 通訊軟體。部分社群和通知頻道 | Mac App Store | 活躍使用 |
| **Keynote** | Apple 簡報軟體 | Mac App Store (內建) | 偶爾使用 |
| **Numbers** | Apple 試算表軟體 | Mac App Store (內建) | 偶爾使用 |
| **Pages** | Apple 文書軟體 | Mac App Store (內建) | 偶爾使用 |
| **Xcode** | Apple 開發環境。提供 Command Line Tools + iOS 開發 | Mac App Store | 核心依賴 |
| **AltServer** | Riley Testut 的 iOS 側載工具。不需越獄安裝第三方 app 到 iPhone | `/Applications/` (手動) | 偶爾使用 |
| **iloader** | iOS 裝置管理/資料傳輸工具。最近使用：2/15 | `/Applications/` (手動) | 偶爾使用 |
| **OpenClaw** | AI 法律文件分析工具 | `/Applications/` (手動) | 保留 |
| **Nerd Font** | Meslo LG Nerd Font。終端機用的等寬字體，含圖示字元（tmux/oh-my-zsh 圖示依賴） | `brew install --cask font-meslo-lg-nerd-font` | 核心依賴 |

---

## 設定備份機制

### Config 備份等級

| 等級 | 策略 | 範例 |
|------|------|------|
| **Git 管理** | 工具自帶 git repo，envkit 只記錄位置 | `~/.claude/` |
| **檔案複製** | envkit 備份到 `configs/` | `.tmux.conf`, `.zshrc`, `.zshenv` |
| **匯出還原** | 工具的 export/import 指令 | iTerm2 Profile JSON, VS Code extensions |
| **雲端同步** | 登入即還原，envkit 只記錄帳號提示 | Chrome, Tailscale |
| **容器備份** | docker-compose.yml + volume dump | PostgreSQL, Redis |
| **不備份** | 安裝後即可用 | ripgrep, bat, fd |

### 關鍵 Config 詳細備份清單

```yaml
# envkit-configs.yaml

git_managed:
  - path: "~/.claude/"
    repo: true
    notes: "agents, rules, hooks, skills, settings — 已有完整 git 追蹤"

file_backup:
  - path: "~/.tmux.conf"
    priority: critical
  - path: "~/.tmux/"
    priority: critical
    notes: "tpm plugins"
  - path: "~/.zshrc"
    priority: critical
  - path: "~/.zshenv"
    priority: critical
  - path: "~/.oh-my-zsh/custom/"
    priority: critical
    notes: "custom plugins, themes, aliases"
  - path: "~/.gitconfig"
    priority: high
  - path: "~/.codex/"
    priority: high
  - path: "~/.gemini/"
    priority: high
  - path: "~/.config/litellm/"
    priority: high

export_restore:
  - tool: iterm2
    export: "iTerm2 → Settings → Profiles → JSON"
    priority: high
  - tool: vscode
    notes: "code CLI 未在 PATH，需先設定再匯出 extensions"
    priority: high
  - tool: logi-options
    export: "~/Library/Application Support/LogiOptionsPlus/"
    priority: medium

cloud_sync:
  - tool: chrome
    method: "Google 帳號登入"
  - tool: tailscale
    method: "帳號登入 + approve device"

container_backup:
  - compose: "infra/docker-compose.yml"
    volumes: ["postgres-data", "redis-data", "rustfs-data"]
    priority: high
```

---

## CLI 介面（`envkit`）

| 指令 | 說明 |
|------|------|
| `envkit snapshot` | 掃描目前環境（apps + CLI + libs + configs），輸出 YAML 快照 |
| `envkit backup` | 備份所有 Tier 1-2 設定檔到 `configs/` |
| `envkit bootstrap [snapshot.yaml]` | 在新機器上依序安裝所有軟體 + 還原設定 |
| `envkit verify [snapshot.yaml]` | 驗證目前環境 vs 快照（列出缺少 / 版本不符） |
| `envkit diff <a.yaml> <b.yaml>` | 比較兩份快照差異 |
| `envkit list [category]` | 列出指定分類的已安裝項目 |

### snapshot 掃描來源

```
envkit snapshot 會自動掃描：
├── brew list --formulae          → CLI 工具
├── brew list --casks             → brew 安裝的 GUI 應用
├── ls /Applications/             → 所有 GUI 應用（含非 brew）
├── npm list -g                   → 全域 Node 套件
├── uv tool list                  → uv 管理的 Python 工具
├── mas list                      → Mac App Store 應用
├── ollama list                   → Ollama 模型
├── docker ps / docker-compose    → OrbStack 容器服務
└── envkit 自有 config 清冊        → 設定檔追蹤狀態
```

---

## Bootstrap Pipeline（安裝順序）

新硬體安裝的正確順序（有依賴關係）：

```
Phase 1: 基礎設施
  ├── Xcode Command Line Tools
  ├── Homebrew
  └── Rosetta 2 (Apple Silicon)

Phase 2: 語言 Runtime
  ├── uv + Python 3.12
  ├── Node.js + pnpm + bun
  └── Go

Phase 3: Shell 環境（Tier 1 設定還原）
  ├── Oh My Zsh + custom plugins
  ├── 還原 .zshrc + .zshenv
  ├── tmux + tpm plugins
  ├── 還原 .tmux.conf
  ├── iTerm2 + Nerd Font + 匯入 Profile
  └── zoxide, bat, fd, fzf

Phase 4: 開發工具
  ├── Git + git-lfs + .gitconfig
  ├── gh (GitHub CLI)
  ├── ripgrep, pandoc, tesseract
  ├── VS Code + extensions
  └── Zed

Phase 5: AI 工具鏈
  ├── Claude Code + 還原 ~/.claude/ (git clone)
  ├── Codex CLI + ~/.codex/
  ├── Gemini CLI + ~/.gemini/
  ├── Ollama + models (nomic-embed-text, qwen2.5:0.5b)
  ├── LiteLLM + config
  ├── mlx + mlx-lm, edge-tts
  └── Claude Squad, Recall

Phase 6: 網路與安全
  ├── Tailscale（登入）
  ├── LuLu（防火牆）
  ├── KnockKnock
  ├── cloudflared
  ├── mosh, gnupg
  └── SSH keys（手動）

Phase 7: 容器與服務
  ├── OrbStack
  └── docker-compose up (postgres, redis, lgtm, rustfs)

Phase 8: GUI 應用
  ├── Chrome（登入 Google 同步）
  ├── Logi Options+（還原設定）
  ├── LibreOffice, LINE, Telegram
  ├── 其他 brew casks
  └── Mac App Store apps (mas install)

Phase 9: 驗證
  └── envkit verify（逐項檢查 + 報告）
```

---

## 目錄結構

```
stations/envkit/
├── README.md               ← 本文件
├── envkit.py               ← CLI 主程式
├── inventory.yaml          ← 完整環境清冊（source of truth）
├── configs/                ← Tier 1-2 設定檔備份
│   ├── tmux/               ← .tmux.conf + .tmux/
│   ├── zsh/                ← .zshrc + .zshenv + oh-my-zsh/custom/
│   ├── git/                ← .gitconfig
│   ├── codex/              ← .codex/ 設定
│   ├── gemini/             ← .gemini/ 設定
│   ├── litellm/            ← LiteLLM 設定
│   ├── iterm2/             ← 匯出的 Profile JSON
│   ├── vscode/             ← settings.json + extensions.txt
│   └── logi/               ← Logi Options+ 設定
├── bootstrap/
│   ├── phase1-infra.sh
│   ├── phase2-runtime.sh
│   ├── phase3-shell.sh     ← Shell 環境 + Tier 1 config 還原
│   ├── phase4-tools.sh
│   ├── phase5-ai.sh
│   ├── phase6-network.sh
│   ├── phase7-services.sh
│   ├── phase8-apps.sh
│   └── phase9-verify.sh
├── collectors/
│   ├── brew.sh
│   ├── apps.sh             ← /Applications/ 掃描
│   ├── npm.sh
│   ├── uv.sh
│   ├── mas.sh
│   ├── ollama.sh
│   ├── docker.sh           ← OrbStack 容器掃描
│   └── vscode.sh
└── snapshots/              ← 歷史快照
    └── mac-mini-YYYY-MM-DD.yaml
```

## 遷移計劃

1. 以本文件為基礎，產生初始 `inventory.yaml`（已掃描完成）
2. 備份 Tier 1 config（tmux, zsh, Claude Code 位置記錄）
3. 備份 Tier 2 config（iTerm2 匯出, VS Code extensions, Codex/Gemini/LiteLLM）
4. 實作 `envkit snapshot`（collectors 自動掃描）
5. 實作 `envkit backup`（config 備份）
6. 撰寫 bootstrap pipeline（9 個 phase 腳本）
7. 實作 `envkit verify`（驗證機制）
8. 在另一台機器測試 `envkit bootstrap`（真實驗證）
9. 確認穩定後，歸檔 `~/dotfiles/`

## 參考

- 現有 dotfiles（將被取代）：`~/dotfiles/`
- Claude Code config：`~/.claude/`（git repo，55+ 檔案）
- 硬體：Mac Mini M4 + BenQ 2K 非 Retina 螢幕
- 網路：Tailscale `100.104.237.69`
