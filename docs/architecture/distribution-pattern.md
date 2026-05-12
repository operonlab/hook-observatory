---
doc_version: 1
status: design-spec
last_updated: 2026-05-12
---

# Distribution Pattern — workshop 模組對外開源的標準作法

> 把內部 module / station 對外開源時的統一模式。事實源永遠在 workshop，開源 repo 是「下游發行版」，不是 sibling。

## 為什麼需要這份文件

少爺已經有三個內部模組正在或將要開源：

| 內部位置（上游 = 事實源） | 開源 repo（下游 = 發行版） | 現況 |
|--------------------------|---------------------------|------|
| `stations/hook-observatory/` | `operonlab/hook-observatory` | 已釋出 |
| `stations/session-channel/` | `operonlab/session-channel`（v0.2 規劃中）| Phase 8 進行中 |
| `core/src/modules/memvault/` | `joneshong/memvault-os` | worktree 開發中 |

過去每個案子各自設計部署細節，會踩到同一批雷三次。這份文件把共通骨架定下來，後續新模組開源走同一條路。

## 核心心智：上游 / 下游，不是雙胞胎

```
workshop monorepo (上游, 事實源)
  └── stations/<name>/ 或 core/src/modules/<name>/   ← 少爺每天改這裡
                │
                │  git subtree split + adapter shim
                ▼
<org>/<name>-os 或 <org>/<name> (下游, 發行版)
  ├── core/        ← subtree 同步進來，不手改
  ├── deploy/      ← 下游獨有（自帶 PG/Redis、docker-compose）
  ├── adapter/     ← 下游獨有（取代 workshop infra）
  └── scripts/sync-from-workshop.sh
```

三條鐵律：

1. **單一事實源** — workshop 內版本是主開發地，下游 repo 只接收同步，不在下游手改核心
2. **Adapter 隔離** — 下游用 adapter shim 替換 workshop infra（auth / event bus / DB / Redis），核心邏輯不感知
3. **機械同步** — 用 `git subtree split` 自動化，不手抄

## 三類 Adapter Shim（下游獨有，上游不需要）

開源使用者沒有 workshop infra，必須補上殼層：

### A. Auth Adapter

| Workshop 內 | 下游 standalone |
|------------|----------------|
| `core/src/modules/auth/` itsdangerous signed cookie + Redis session | `adapter/auth_standalone.py`：單機 session token（環境變數或 SQLite） |
| RBAC + ABAC + Space 權限 | 退化為單一 user / admin token |

### B. Event Bus Adapter

| Workshop 內 | 下游 standalone |
|------------|----------------|
| `core/src/events/` Redis Streams + consumer group | `adapter/eventbus_inmem.py`：in-memory `asyncio.Queue` |
| 跨模組 publish/subscribe | 同 process pub/sub，重啟即清空 |

### C. Deploy Bundle

| Workshop 內 | 下游 standalone |
|------------|----------------|
| 共用 workshop PG（per-module schema） | `deploy/docker-compose.yml` 自帶 PG（單 schema） |
| 共用 workshop Redis | `deploy/docker-compose.yml` 自帶 Redis（單 db） |
| `infra/nginx/...` workshop 共用反代 | `deploy/Caddyfile` 或省略（直連 service port） |
| Schema 跟 Alembic 走 | `deploy/bootstrap.sql` 一次性建表 |

> 不一定每個下游都需要 A/B/C 全套 — 例如 hook-observatory 沒有 auth 需求，session-channel Python 版本身就不依賴 workshop event bus。各案視情況挑。

## 同步流程（標準操作）

複用 `~/.claude/rules/operonlab-release.md` 的 subtree pattern：

```bash
# 一次性設定 remote
git remote add <downstream-name> https://github.com/<org>/<repo>

# 同步（每次 workshop 主版有改）
git subtree split --prefix=stations/<name> -b <name>-sync-temp
git push <downstream-name> <name>-sync-temp:main
git branch -D <name>-sync-temp
```

下游 repo 內 `adapter/` 與 `deploy/` 不會被 subtree split 觸碰（因為它們不存在 workshop 內）— 維護下游 repo 上 master 分支，subtree 推送結果會 merge 進去。

實務作法：把上面三行包成 `scripts/distribute.sh <module> <downstream>`，少爺執行一句即可。腳本待寫，目前各專案各自實作。

## 適用 / 不適用

**適用**：
- 內部模組想要對外開源
- 核心邏輯穩定，介面變動緩慢
- 願意接受「下游永遠落後上游 N 個 commit」

**不適用**：
- 開源版本要拿外部 PR 進來 → subtree 反向同步複雜，要走 fork + cherry-pick
- 模組強耦合 workshop 多個其他模組 → adapter shim 寫不完，先考慮解耦
- 模組高頻迭代（每天破壞性改動）→ 下游使用者跟不上，應等穩定再開源

## 少爺自己怎麼用？

關鍵設計選擇：**少爺自己不裝下游發行版**。

| Service | 少爺自己用 | 外人用 |
|---------|----------|-------|
| memvault | `core/src/modules/memvault/`（共用 workshop PG / Redis / auth）| `memvault-os` docker-compose（自帶 PG / Redis） |
| session-channel | `stations/session-channel/`（Python，直接跑）| `operonlab/session-channel` |
| hook-observatory | `stations/hook-observatory/`（workshop 內）| `operonlab/hook-observatory` |

這樣避開「自己也裝下游 → PG/Redis 雙開銷」的反模式（少爺先前正確識別出來的痛點）。

## 與 rewrite-status.md 的關係

- 本文檔是**規範**（怎麼做）
- [rewrite-status.md](./rewrite-status.md) 是**狀態**（誰處在哪一步）
- 每個下游發行版的 status 列在 rewrite-status.md 的「開源發行版」段

## 後續工作（規格 → 落地）

1. 把 `scripts/distribute.sh` 落地成共用工具（取代 hook-observatory 各自寫的腳本）
2. memvault-os adapter shim 三件（`auth_standalone.py` / `eventbus_inmem.py` / `deploy/docker-compose.yml`）落地，在 `.worktrees/feature/memvault-os/` 內實作
3. session-channel Python 版 v0.2 開源前，按本文件檢查 `adapter/` 是否需要（目前評估：CLI 模式不依賴 workshop infra，可能 adapter 空集合）
