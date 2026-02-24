# EnvKit 工作站

> 環境快照 + 一鍵移植 — 完整記錄目前環境配置，讓新硬體快速達到相同工作狀態。

## 定位

Workshop `stations/` 下的獨立工作站。少爺的環境已經配置得很舒服了，EnvKit 的目標是：
1. **快照當前環境** — 詳盡記錄所有已安裝的 app、lib、config
2. **一鍵復原** — 新硬體跑一個腳本就能達到相同工作狀態
3. **持續同步** — 環境變更時自動更新清冊

## V1 資產（~/dotfiles/）

`~/dotfiles/` 已有良好基礎，但缺少系統性管理：

| 元件 | 位置 | 狀態 |
|------|------|------|
| `lists/brew-formulae.txt` | ~/dotfiles/lists/ | ✅ 有清單 |
| `lists/brew-casks.txt` | ~/dotfiles/lists/ | ✅ 有清單 |
| `lists/npm-globals.txt` | ~/dotfiles/lists/ | ✅ 有清單 |
| `lists/uv-tools.txt` | ~/dotfiles/lists/ | ✅ 有清單 |
| `lists/pip-packages.txt` | ~/dotfiles/lists/ | ✅ 有清單 |
| `lists/mas-apps.txt` | ~/dotfiles/lists/ | ✅ Mac App Store |
| `lists/ollama-models.txt` | ~/dotfiles/lists/ | ✅ 有清單 |
| `lists/vscode-extensions.txt` | ~/dotfiles/lists/ | ✅ 有清單 |
| `configs/` | ~/dotfiles/configs/ | ⚠️ 有 tmux, zsh 等，但不完整 |
| `scripts/` | ~/dotfiles/scripts/ | ⚠️ 有 bootstrap 腳本，但分散 |

### V1 缺少的（少爺說「不是我要的」）

- ❌ 沒有 **分類清冊**（哪些是開發工具、哪些是日常 app、哪些是 AI 工具）
- ❌ 沒有 **config 完整性**（只有部分 dotfiles，缺少 Claude/Codex/Gemini 設定）
- ❌ 沒有 **一鍵 bootstrap** 的順序管理（安裝順序有依賴關係）
- ❌ 沒有 **驗證機制**（跑完 bootstrap 不知道有沒有漏裝）
- ❌ 沒有 **diff 報告**（兩台機器之間的環境差異比較）

## V2 目標

### 1. 分類清冊（Inventory）

將所有已安裝的軟體分類並加上說明：

```yaml
# envkit-inventory.yaml
categories:
  ai_tools:
    description: "AI CLI 工具與服務"
    items:
      - name: claude-code
        install: "uv tool install claude-code"
        config: "~/.claude/"
        notes: "主力 AI CLI"
      - name: codex-cli
        install: "brew install codex"
        config: "~/.codex/"
        notes: "OpenAI CLI"
      - name: gemini-cli
        install: "brew install gemini"
        config: "~/.gemini/"
        notes: "Google CLI"
      - name: ollama
        install: "brew install ollama"
        config: "~/.ollama/"
        models: ["nomic-embed-text"]
        notes: "本地 LLM + Embedding"
      - name: litellm
        install: "pip install litellm"
        config: "~/.config/litellm/"
        notes: "統一 LLM Proxy"

  terminal:
    description: "終端環境"
    items:
      - name: iterm2
        install: "brew install --cask iterm2"
        config: "~/Library/Preferences/com.googlecode.iterm2.plist"
        notes: "主力終端（Catppuccin Mocha + Hotkey Window）"
      - name: oh-my-zsh
        install: "sh -c \"$(curl -fsSL ...)\""
        config: "~/.zshrc"
        plugins: [git, z, zsh-autosuggestions, zsh-syntax-highlighting]
      - name: tmux
        install: "brew install tmux"
        config: "~/.tmux.conf"
        notes: "多工管理"

  development:
    description: "開發工具"
    items:
      - name: python
        install: "uv python install 3.12"
        version: "3.12"
        manager: "uv"
      - name: node
        install: "brew install node"
        manager: "pnpm"
      - name: docker
        install: "brew install --cask docker"
      # ...

  productivity:
    description: "日常應用"
    items:
      - name: raycast
        install: "brew install --cask raycast"
      - name: arc
        install: "brew install --cask arc"
      # ...
```

### 2. Config 映射表

清楚標記每個工具的設定檔位置 + 是否已被 dotfiles 追蹤：

| 工具 | Config 位置 | 追蹤狀態 | 備註 |
|------|-----------|---------|------|
| Claude Code | `~/.claude/` | ✅ git repo | 55+ 設定檔 |
| Codex CLI | `~/.codex/` | ✅ dotfiles | |
| Gemini CLI | `~/.gemini/` | ✅ dotfiles | |
| Oh My Zsh | `~/.zshrc`, `~/.zshenv` | ✅ dotfiles | |
| tmux | `~/.tmux.conf` | ✅ dotfiles | |
| iTerm2 | `~/Library/Preferences/` | ⚠️ 需匯出 | Profile JSON |
| Git | `~/.gitconfig` | ✅ dotfiles | |
| SSH | `~/.ssh/config` | ❌ 手動 | 含金鑰，不 git |
| LiteLLM | `~/.config/litellm/` | ⚠️ 部分 | |

### 3. Bootstrap Pipeline（安裝順序）

新硬體安裝的正確順序（有依賴關係）：

```
Phase 1: 基礎設施
  ├── Xcode Command Line Tools
  ├── Homebrew
  └── Rosetta 2 (Apple Silicon)

Phase 2: 語言 Runtime
  ├── Python (uv)
  ├── Node.js (pnpm)
  └── Rust (rustup)

Phase 3: 終端環境
  ├── iTerm2
  ├── Oh My Zsh + 插件
  ├── tmux + config
  └── GNU Stow (symlink dotfiles)

Phase 4: 開發工具
  ├── Docker Desktop
  ├── VS Code + extensions
  ├── Git config
  └── SSH keys (手動)

Phase 5: AI 工具
  ├── Claude Code (uv)
  ├── Codex CLI (brew)
  ├── Gemini CLI (brew)
  ├── Ollama + models
  └── LiteLLM

Phase 6: 服務
  ├── PostgreSQL
  ├── Redis
  └── Nginx

Phase 7: 應用程式
  ├── Homebrew Casks (GUI apps)
  └── Mac App Store (mas)

Phase 8: 驗證
  └── envkit verify（逐項檢查）
```

### 4. 驗證與 Diff

```bash
# 在目前機器上快照
envkit snapshot > ~/dotfiles/snapshots/mac-mini-2026-02.yaml

# 在新機器上執行 bootstrap 後驗證
envkit verify ~/dotfiles/snapshots/mac-mini-2026-02.yaml
# Output:
# ✅ 128/135 items installed
# ⚠️ 5 items version mismatch
# ❌ 2 items missing: [mas:app1, brew:formula2]

# 兩台機器比較差異
envkit diff mac-mini.yaml macbook.yaml
```

## CLI 介面（`envkit`）

| 指令 | 說明 |
|------|------|
| `envkit snapshot` | 掃描目前環境，輸出 YAML 快照 |
| `envkit bootstrap [snapshot.yaml]` | 依序安裝所有軟體 |
| `envkit verify [snapshot.yaml]` | 驗證目前環境 vs 快照 |
| `envkit diff <a.yaml> <b.yaml>` | 比較兩份快照差異 |
| `envkit update-lists` | 更新 ~/dotfiles/lists/ 清單 |
| `envkit inventory` | 互動式檢視分類清冊 |

## API 端點（`/api/stations/envkit/`，可選）

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/inventory` | 分類清冊 |
| GET | `/configs` | Config 映射表 |
| GET | `/snapshots` | 歷史快照列表 |
| POST | `/snapshot` | 觸發快照 |
| POST | `/verify` | 驗證 vs 快照 |

## Workbench Widget（可選）

```
┌─── EnvKit ──────────────────────────────┐
│                                         │
│  🖥️ Mac Mini (2026-02-24 snapshot)      │
│                                         │
│  AI Tools:     5/5  ✅                  │
│  Terminal:     4/4  ✅                  │
│  Development: 12/12 ✅                  │
│  Services:     3/3  ✅                  │
│  Apps:        28/30 ⚠️ (2 outdated)     │
│                                         │
│  Last snapshot: 2026-02-24              │
│  [Update Snapshot] [View Inventory →]   │
└─────────────────────────────────────────┘
```

## 目錄結構

```
stations/envkit/
├── README.md               ← 本文件
├── envkit.py               ← CLI 主程式
├── inventory.yaml          ← 分類清冊（source of truth）
├── config-map.yaml         ← Config 映射表
├── bootstrap/
│   ├── phase1-infra.sh     ← Xcode, Homebrew, Rosetta
│   ├── phase2-runtime.sh   ← Python, Node, Rust
│   ├── phase3-terminal.sh  ← iTerm2, Oh My Zsh, tmux
│   ├── phase4-devtools.sh  ← Docker, VS Code, Git
│   ├── phase5-ai.sh        ← Claude, Codex, Gemini, Ollama
│   ├── phase6-services.sh  ← PostgreSQL, Redis, Nginx
│   ├── phase7-apps.sh      ← Casks + Mac App Store
│   └── phase8-verify.sh    ← 逐項驗證
├── collectors/
│   ├── brew.sh             ← 收集 brew formulae + casks
│   ├── npm.sh              ← 收集 global npm packages
│   ├── uv.sh               ← 收集 uv tools
│   ├── mas.sh              ← 收集 Mac App Store apps
│   └── ollama.sh           ← 收集 Ollama models
└── snapshots/              ← 歷史快照存放
```

## 與 ~/dotfiles/ 的關係

```
~/dotfiles/           ← 設定檔 (configs) + 安裝清單 (lists) + 基礎腳本 (scripts)
  │                      已有 GNU Stow symlink 管理
  │
stations/envkit/      ← 環境管理引擎
  ├── inventory.yaml  ← 比 dotfiles/lists/ 更完整的分類清冊
  ├── bootstrap/      ← 有順序的安裝流程（取代 dotfiles/scripts/）
  └── collectors/     ← 自動更新 dotfiles/lists/ 的工具
```

**原則**：dotfiles 管「設定檔」，envkit 管「環境全貌」。envkit 的 collectors 會自動同步到 dotfiles/lists/。

## 遷移計劃

1. 盤點目前 ~/dotfiles/ 已有清單，產生初始 `inventory.yaml`
2. 建立 `config-map.yaml`（所有工具的 config 位置 + 追蹤狀態）
3. 實作 `envkit snapshot`（掃描目前環境）
4. 實作 `envkit verify`（驗證機制）
5. 撰寫 bootstrap pipeline（8 個 phase 腳本）
6. 實作 `envkit diff`（雙機比較）
7. （可選）建立 Workbench Widget

## 參考

- 現有 dotfiles：`~/dotfiles/`
- Claude Code config：`~/.claude/`（git repo，55+ 檔案）
- GNU Stow：symlink 管理工具
- daily sync：`~/dotfiles/auto-sync` 每日同步到 dotfiles repo
