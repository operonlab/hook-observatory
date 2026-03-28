# Anvil Station

Skill 生命週期管理服務。基於 FastAPI 的獨立 Station，負責 Skill 註冊、呼叫遙測、
評估追蹤與自我修正記錄。

## 功能

- **Skill 註冊** -- 自動掃描 `~/.claude/skills/` 目錄，解析 SKILL.md frontmatter，
  註冊 Skill metadata 至 PostgreSQL
- **呼叫遙測** -- 接收 Hook 遙測資料，記錄每次 Skill 呼叫的持續時間、成功率、錯誤訊息
- **統計分析** -- 全域與個別 Skill 的呼叫統計、7 日趨勢、常見錯誤排行
- **評估追蹤** -- 三角度評估（Grading / Comparator / Analyzer）結果存儲與 Benchmark 趨勢
- **自我修正** -- 修正提案、審批、執行、回退的完整生命週期

## 啟動

```bash
cd stations/anvil
uv run anvil-server
```

預設監聽 `127.0.0.1:10301`。

## 設定

設定檔路徑：`~/.anvil/config.toml`

```toml
port = 10301
host = "127.0.0.1"
database_url = "postgresql+asyncpg://joneshong:REDACTED@localhost/workshop"
skills_dir = "~/.claude/skills"
```

環境變數覆蓋：`ANVIL_PORT`、`ANVIL_HOST`、`ANVIL_DATABASE_URL`、`ANVIL_SKILLS_DIR`

## API 端點

所有端點前綴為 `/api/anvil`。

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/health` | 健康檢查 |
| POST | `/skills` | 註冊/更新 Skill |
| GET | `/skills` | 列出所有 Skill |
| GET | `/skills/{name}` | Skill 詳情（含統計） |
| PUT | `/skills/{name}` | 更新 Skill metadata |
| DELETE | `/skills/{name}` | 封存 Skill（soft delete） |
| POST | `/invocations` | 記錄呼叫 |
| GET | `/invocations` | 列出呼叫記錄 |
| GET | `/stats` | 全域統計 |
| GET | `/stats/{name}` | 個別 Skill 統計 |
| POST | `/evaluations/{name}` | 觸發評估 |
| GET | `/evaluations` | 列出評估 |
| GET | `/evaluations/{name}` | 最新評估 |
| PUT | `/evaluations/{eval_id}` | 更新評估結果 |
| GET | `/evaluations/{name}/benchmark` | Benchmark 資料 |
| POST | `/corrections` | 提出修正 |
| GET | `/corrections` | 列出修正 |
| PUT | `/corrections/{id}` | 更新修正狀態 |

## 資料庫

使用 PostgreSQL schema `anvil`，包含 6 個資料表：
`skills`、`invocations`、`skill_versions`、`evaluations`、`eval_definitions`、`corrections`。

啟動時自動建立 schema 與資料表。
