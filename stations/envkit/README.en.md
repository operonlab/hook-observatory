---
source_hash: 76332f9d
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# EnvKit Workstation

> Complete environment management — replaces ~/dotfiles/, records all installed applications, tools, settings, and allows one-click restoration to new hardware.

## Positioning

An independent workstation under Workshop `stations/`. **Replaces** `~/dotfiles/` to become the single source of truth for environment management.

The three core tasks of EnvKit:
1.  **Snapshot** — Scan all installed apps, CLIs, libraries, and system settings on the Mac Mini.
2.  **Configuration Backup** — Back up the configuration files for all important tools (tmux, zsh, Claude Code, etc.).
3.  **One-Click Restore** — Run a script on new hardware to restore to the exact same working state.

## V1 Assets (~/dotfiles/ → To be replaced)

`~/dotfiles/` has installation lists + a basic bootstrap, but the user considers it "not what I want":

| What it has | What it's missing |
|---|---|
| brew formulae/casks list | No categorization (e.g., which are network tools, which are development tools) |
| npm/uv/pip lists | No complete list of GUI applications |
| Partial configs (tmux, zsh) | Missing configurations for Claude Code, iTerm2, Logi Options+, etc. |
| Basic bootstrap script | No installation order management, verification, or diffing |

**Migration Plan**: Once EnvKit is stable, `~/dotfiles/` will be archived and deprecated.

---

## Environment Inventory (Actual scan on 2026-02-24)

### Tier 1 — Core Configurations (config backup is mandatory)

The **configuration files** for these tools are the most important assets; losing them means starting from scratch:

| Tool | Purpose | Config Location | Backup Strategy |
|---|---|---|---|
| **Claude Code** | Primary AI CLI | `~/.claude/` | Existing git repo (55+ files: agents, rules, hooks, skills, settings) |
| **tmux** | Multiplex terminal | `~/.tmux.conf` + `~/.tmux/` (tpm plugins) | envkit file backup |
| **Oh My Zsh** | Shell environment | `~/.zshrc`, `~/.zshenv`, `~/.oh-my-zsh/custom/` | envkit file backup |

### Tier 2 — Important Tools (installation + config need backup)

| Tool | Purpose | Installation Method | Config Location |
|---|---|---|---|
| **iTerm2** | Primary terminal | `brew install --cask iterm2` | Profile JSON export |
| **VS Code** | Code editor | `/Applications/` (manual install) | settings.json + extensions list |
| **Tailscale** | Remote access VPN | Mac App Store (`mas install 1475387142`) | Restores on login |
| **LuLu** | Firewall | `brew install --cask lulu` | Firewall rules |
| **OrbStack** | Docker containers | `brew install --cask orbstack` | `~/.orbstack/` |
| **Logi Options+** | Mouse/Keyboard settings | `/Applications/` (official website install) | `~/Library/Application Support/LogiOptionsPlus/` |
| **Chrome** | Browser | `/Applications/` (official website install) | Google account sync on login |

### Tier 3 — CLI Toolchain

**AI Tools**:

| Tool | Description | Installation Method | Status |
|---|---|---|---|
| **Gemini CLI** | Google's AI CLI, similar to Claude Code but uses Gemini models. One of the three brains in the strategy. | `brew install gemini-cli` | Actively used |
| **Codex CLI** | OpenAI's AI CLI, another of the three brains. Good for small, deterministic tasks. | `brew install --cask codex` | Actively used |
| **Ollama** | Run LLM / Embedding models locally. Currently running nomic-embed-text (for KAS vectorization) + qwen2.5:0.5b (for lightweight testing). | `brew install ollama` | Actively used |
| **LiteLLM** | Unified LLM API Proxy for routing across multiple providers. Used for API services in custom agent scenarios like Agent SDK. | `uv tool install litellm` | Actively used |
| **mlx-lm** | Apple Silicon optimized local LLM inference framework. Runs MLX format models (e.g., Qwen3-TTS). | `uv tool install mlx-lm` | Occasional experiments |
| **edge-tts** | Microsoft Edge's free TTS engine. Used for voice notifications in Claude Code sessions. | `uv tool install edge-tts` | Actively used |
| **Claude Squad** | TUI multi-agent manager. Manages multiple Claude Code instances simultaneously with visual status. | `brew install claude-squad` | Actively used |
| **Recall** | Full-text search TUI for Claude Code session history. Search past conversations to find forgotten details. | `brew install recall` | Actively used |
| **summarize** | Webpage/link → plain text → summary. Quickly converts a URL into clean text. | `brew install steipete/tap/summarize` | Occasionally used |
| **remindctl** | Apple Reminders CLI. Quickly create/view reminders from the terminal. | `brew install steipete/tap/remindctl` | Occasionally used |

**Development Tools**:

| Tool | Description | Installation Method | Status |
|---|---|---|---|
| **uv** | Ultra-fast Python package manager written in Rust. Manages Python 3.12 + virtual environments + tool installations. | `brew install uv` | Core tool |
| **bun** | Ultra-fast JS runtime + bundler + package manager. Some projects use bun instead of node. | `brew install bun` | Actively used |
| **Node.js** | JS runtime. node @Library/Metadata/CoreSpotlight/SpotlightKnowledgeEvents/index.V2/events/12/processingState/cs_pc_c/evt_journalAttr_52ED947C-E89F-4B3C-8DB7-730BDBEBFAA9_12203010_214.processed is the LTS version. | `brew install node` + `node @22` | Core tool |
| **pnpm** | Fast, disk space-efficient Node package manager. Workshop frontend uses pnpm. | `npm install -g pnpm` | Core tool |
| **Go** | Go language. A dependency for some community tools (claude-squad, recall). | `brew install go` | Indirect dependency |
| **gh** | GitHub CLI. Create PRs, view Issues, manage repos, etc. | `brew install gh` | Actively used |
| **git-lfs** | Git Large File Storage. For versioning large binary files. | `brew install git-lfs` | Occasionally needed |

**Search/Text Processing**:

| Tool | Description | Installation Method | Status |
|---|---|---|---|
| **ripgrep** | Ultra-fast regex search (10x+ faster than grep). Claude Code also uses it internally. | `brew install ripgrep` | Core tool |
| **fzf** | Fuzzy finder. Interactive filter for Ctrl+R history search, file search, etc. | `brew install fzf` | Core tool |
| **bat** | A cat clone with syntax highlighting, line numbers, and Git integration. | `brew install bat` | Actively used |
| **fd** | A simpler and faster alternative to find. | `brew install fd` | Actively used |
| **zoxide** | A smarter cd command that remembers frequently visited directories. `z foo` jumps directly. | `brew install zoxide` | Actively used |
| **pandoc** | Universal document converter. Markdown↔HTML↔PDF↔DOCX, etc. | `brew install pandoc` | Occasionally used |
| **tesseract** | Open-source OCR engine. Image to text recognition, tesseract-lang provides multi-language support. | `brew install tesseract` + `tesseract-lang` | Occasionally used |

**Networking/System**:

| Tool | Description | Installation Method | Status |
|---|---|---|---|
| **mosh** | An alternative to SSH that supports roaming and provides better latency. More stable for remote connections. | `brew install mosh` | Occasionally used |
| **cloudflared** | Cloudflare Tunnel client. Securely expose local services to the internet (without opening ports). | `brew install cloudflared` | Occasionally used |
| **ttyd** | Share your terminal as a web application. An underlying component of tmux-webui. | `brew install ttyd` | Actively used |
| **mc** | Midnight Commander, a dual-pane file manager for the terminal. Quickly browse/move files. | `brew install mc` | Occasionally used |
| **lynis** | System security auditing tool. Scans macOS security settings and provides recommendations. | `brew install lynis` | Occasional audits |
| **gnupg** | GPG encryption/signing tool. For signing Git commits and encrypting files. | `brew install gnupg` | Occasionally needed |
| **ffmpeg** | Universal media processing tool. Video conversion, splitting, merging, audio processing, etc. | `brew install ffmpeg` | Actively used |
| **mlx** | Native ML framework for Apple Silicon (C++ backend). An underlying dependency for mlx-lm. | `brew install mlx` | Indirect dependency |

**Global npm Packages**:

| Package | Description | Status |
|---|---|---|
| **@google/clasp** | Google Apps Script CLI. Deploy/manage Google Apps Script projects from the terminal. | Occasionally used |
| **docx** | Node.js Word document generator. Used by the docx skill to create .docx reports. | Actively used |
| **pptxgenjs** | Node.js PowerPoint generator. Used by the pptx skill to create .pptx presentations. | Actively used |

### Tier 4 — Docker Services (OrbStack)

All backend services run in containers via OrbStack, not directly on macOS:

| Container | Image | Purpose |
|---|---|---|
| **ws-infra-postgres-1** | `postgres:16` | Main database |
| **ws-infra-redis-1** | `redis:7-alpine` | Cache + Event Bus |
| **ws-infra-lgtm-1** | `grafana/otel-lgtm:latest` | Observability (Grafana + LGTM) |
| **ws-infra-rustfs-1** | `rustfs/rustfs:latest` | Object storage (S3-compatible) |

All infrastructure is managed by `docker compose -p ws-infra`, defined in `infra/docker/docker-compose.yml`.

Backup strategy: `docker-compose.yml` + volume backup

### Tier 5 — Other GUI Applications

| Application | Description | Installation Method | Status |
|---|---|---|---|
| **Zed** | High-performance code editor written in Rust. A lightweight alternative to VS Code with fast startup. | `brew install --cask zed` | Occasionally used |
| **LibreOffice** | Free office suite. Open/edit Office format files. | `brew install --cask libreoffice` | Occasionally used |
| **KnockKnock** | Security tool from Objective-See. Scans all persistent components on macOS (launch items, kernel extensions, etc.). | `brew install --cask knockknock` | Occasional audits |
| **CC Switch** | Claude Code multi-account switching tool. Quickly switch between different Anthropic accounts. | `brew install --cask cc-switch` | Actively used |
| **LINE** | Messaging app. Daily communication + future LINE Bot Bridge. | Mac App Store | Actively used |
| **Telegram** | Messaging app. Some community and notification channels. | Mac App Store | Actively used |
| **Keynote** | Apple's presentation software. | Mac App Store (built-in) | Occasionally used |
| **Numbers** | Apple's spreadsheet software. | Mac App Store (built-in) | Occasionally used |
| **Pages** | Apple's word processing software. | Mac App Store (built-in) | Occasionally used |
| **Xcode** | Apple's development environment. Provides Command Line Tools + iOS development. | Mac App Store | Core dependency |
| **AltServer** | Riley Testut's iOS sideloading tool. Install third-party apps on iPhone without jailbreaking. | `/Applications/` (manual) | Occasionally used |
| **iloader** | iOS device management/data transfer tool. Last used: 2/15. | `/Applications/` (manual) | Occasionally used |
| **OpenClaw** | AI legal document analysis tool. | `/Applications/` (manual) | Kept |
| **Nerd Font** | Meslo LG Nerd Font. A monospaced font for terminals with icon characters (dependency for tmux/oh-my-zsh icons). | `brew install --cask font-meslo-lg-nerd-font` | Core dependency |

---

## Configuration Backup Mechanism

### Config Backup Tiers

| Tier | Strategy | Example |
|---|---|---|
| **Git Managed** | Tool has its own git repo, envkit just records the location. | `~/.claude/` |
| **File Copy** | envkit backs up files to `configs/`. | `.tmux.conf`, `.zshrc`, `.zshenv` |
| **Export/Restore** | Tool's export/import commands. | iTerm2 Profile JSON, VS Code extensions |
| **Cloud Sync** | Restore on login, envkit just prompts for account. | Chrome, Tailscale |
| **Container Backup** | docker-compose.yml + volume dump. | PostgreSQL, Redis |
| **No Backup** | Usable immediately after installation. | ripgrep, bat, fd |

### Detailed Backup List for Key Configs

```yaml
# envkit-configs.yaml

git_managed:
  - path: "~/.claude/"
    repo: true
    notes: "agents, rules, hooks, skills, settings — already fully tracked by git"

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
    notes: "code CLI is not in PATH, needs setup before exporting extensions"
    priority: high
  - tool: logi-options
    export: "~/Library/Application Support/LogiOptionsPlus/"
    priority: medium

cloud_sync:
  - tool: chrome
    method: "Log in to Google account"
  - tool: tailscale
    method: "Log in to account + approve device"

container_backup:
  - compose: "infra/docker-compose.yml"
    volumes: ["postgres-data", "redis-data", "rustfs-data"]
    priority: high
```

---

## CLI Interface (`envkit`)

| Command | Description |
|---|---|
| `envkit snapshot` | Scans the current environment (apps + CLIs + libs + configs) and outputs a YAML snapshot. |
| `envkit backup` | Backs up all Tier 1-2 configuration files to `configs/`. |
| `envkit bootstrap [snapshot.yaml]` | Sequentially installs all software and restores settings on a new machine. |
| `envkit verify [snapshot.yaml]` | Verifies the current environment against a snapshot (lists missing items / version mismatches). |
| `envkit diff <a.yaml> <b.yaml>` | Compares the differences between two snapshots. |
| `envkit list [category]` | Lists installed items in a specific category. |

### Snapshot Scan Sources

```
envkit snapshot automatically scans:
├── brew list --formulae          → CLI tools
├── brew list --casks             → GUI apps installed via brew
├── ls /Applications/             → All GUI apps (including non-brew)
├── npm list -g                   → Global Node packages
├── uv tool list                  → Python tools managed by uv
├── mas list                      → Mac App Store apps
├── ollama list                   → Ollama models
├── docker ps / docker-compose    → OrbStack container services
└── envkit's own config list      → Configuration file tracking status
```

---

## Bootstrap Pipeline (Installation Order)

The correct installation order for new hardware (due to dependencies):

```
Phase 1: Basic Infrastructure
  ├── Xcode Command Line Tools
  ├── Homebrew
  └── Rosetta 2 (Apple Silicon)

Phase 2: Language Runtimes
  ├── uv + Python 3.12
  ├── Node.js + pnpm + bun
  └── Go

Phase 3: Shell Environment (Tier 1 config restore)
  ├── Oh My Zsh + custom plugins
  ├── Restore .zshrc + .zshenv
  ├── tmux + tpm plugins
  ├── Restore .tmux.conf
  ├── iTerm2 + Nerd Font + import Profile
  └── zoxide, bat, fd, fzf

Phase 4: Development Tools
  ├── Git + git-lfs + .gitconfig
  ├── gh (GitHub CLI)
  ├── ripgrep, pandoc, tesseract
  ├── VS Code + extensions
  └── Zed

Phase 5: AI Toolchain
  ├── Claude Code + restore ~/.claude/ (git clone)
  ├── Codex CLI + ~/.codex/
  ├── Gemini CLI + ~/.gemini/
  ├── Ollama + models (nomic-embed-text, qwen2.5:0.5b)
  ├── LiteLLM + config
  ├── mlx + mlx-lm, edge-tts
  └── Claude Squad, Recall

Phase 6: Network and Security
  ├── Tailscale (login)
  ├── LuLu (firewall)
  ├── KnockKnock
  ├── cloudflared
  ├── mosh, gnupg
  └── SSH keys (manual)

Phase 7: Containers and Services
  ├── OrbStack
  └── docker-compose up (postgres, redis, lgtm, rustfs)

Phase 8: GUI Applications
  ├── Chrome (login to Google for sync)
  ├── Logi Options+ (restore settings)
  ├── LibreOffice, LINE, Telegram
  ├── Other brew casks
  └── Mac App Store apps (mas install)

Phase 9: Verification
  └── envkit verify (item-by-item check + report)
```

---

## Directory Structure

```
stations/envkit/
├── README.md               ← This document
├── envkit.py               ← Main CLI program
├── inventory.yaml          ← Complete environment inventory (source of truth)
├── configs/                ← Tier 1-2 configuration backups
│   ├── tmux/               ← .tmux.conf + .tmux/
│   ├── zsh/                ← .zshrc + .zshenv + oh-my-zsh/custom/
│   ├── git/                ← .gitconfig
│   ├── codex/              ← .codex/ settings
│   ├── gemini/             ← .gemini/ settings
│   ├── litellm/            ← LiteLLM settings
│   ├── iterm2/             ← Exported Profile JSON
│   ├── vscode/             ← settings.json + extensions.txt
│   └── logi/               ← Logi Options+ settings
├── bootstrap/
│   ├── phase1-infra.sh
│   ├── phase2-runtime.sh
│   ├── phase3-shell.sh     ← Shell environment + Tier 1 config restore
│   ├── phase4-tools.sh
│   ├── phase5-ai.sh
│   ├── phase6-network.sh
│   ├── phase7-services.sh
│   ├── phase8-apps.sh
│   └── phase9-verify.sh
├── collectors/
│   ├── brew.sh
│   ├── apps.sh             ← /Applications/ scan
│   ├── npm.sh
│   ├── uv.sh
│   ├── mas.sh
│   ├── ollama.sh
│   ├── docker.sh           ← OrbStack container scan
│   └── vscode.sh
└── snapshots/              ← Historical snapshots
    └── mac-mini-YYYY-MM-DD.yaml
```

## Migration Plan

1.  Generate the initial `inventory.yaml` based on this document (scan complete).
2.  Back up Tier 1 configs (record locations for tmux, zsh, Claude Code).
3.  Back up Tier 2 configs (export iTerm2, VS Code extensions, Codex/Gemini/LiteLLM).
4.  Implement `envkit snapshot` (automated scanning with collectors).
5.  Implement `envkit backup` (config backup).
6.  Write the bootstrap pipeline (9 phase scripts).
7.  Implement `envkit verify` (verification mechanism).
8.  Test `envkit bootstrap` on another machine (real-world validation).
9.  Archive `~/dotfiles/` after confirming stability.

## References

-   Existing dotfiles (to be replaced): `~/dotfiles/`
-   Claude Code config: `~/.claude/` (git repo, 55+ files)
-   Hardware: Mac Mini M4 + BenQ 2K non-Retina screen
-   Network: Tailscale `100.104.237.69`
```
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3178ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3756ms
