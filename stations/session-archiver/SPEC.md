# Session Archiver — 冷熱分層壓縮服務

## Context

Claude Code sessions 以 JSONL 存放在 `~/.claude/projects/`，不會自動清理，持續膨脹（目前 1.1GB / 253 sessions）。少爺不想刪除歷史紀錄，而是做冷熱分層：壓縮冷資料、保留 metadata 可搜尋、未來可遷移至 NAS。

整合既有 Workshop 生態系：PostgreSQL 16 + pgvector + SQLAlchemy async + shared embedding/storage + launchd 排程。

### 與 Workshop 冷熱分層對齊

Workshop Core 已完成 4-Phase 冷熱分層（2026-02-28）：
- **HOT**: 主表 + HNSW vector index（memvault blocks, intelflow reports）
- **COLD-ARCHIVE**: archive 表（B-tree/GIN，無向量）
- **COLD-BLOB**: S3（RustFS）offload 大內容，archive 表存 `s3://` URI

Session Archiver 採用相同理念，但資料型態不同（JSONL 檔案而非 DB rows），故分層策略調整：
- 壓縮格式用 zstd（非 S3 blob）——JSONL 壓縮後直接存本機檔案系統
- S3 為可選的遠端備份目的地（FROZEN tier），非必要路徑
- Metadata + summary embedding 存 PostgreSQL（與 Core 共用 Ollama + pgvector）

## Architecture Overview

```
~/.claude/projects/**/*.jsonl    (HOT — 不動)
         │
    [daily 05:15 launchd]
         │
    session-archiver scan → score → archive
         │
         ├── PostgreSQL (workshop_session_archive schema)
         │     └── sessions index + pgvector summary embeddings
         │
         ├── ~/.claude/archive/cold/*.jsonl.zst   (compressed)
         │
         └── metadata stub .json (留在原位，可搜尋)
```

## Session 現況分析 (2026-02-26)

| 指標 | 數值 |
|------|------|
| `~/.claude/` 總大小 | 1.6 GB |
| `projects/` (sessions) | 1.1 GB |
| 主專案 sessions 數 | 253 |
| 最大單一 session | 55 MB（`user` 事件佔 89% — base64 截圖 + 大 tool results） |
| 有 companion dir（被 resume 過） | 128 |
| 純 JSONL（一次性） | 126 |

### 大小分布

```
< 1MB:    141 (56%) ← 大量輕量 session
1-5MB:     74 (29%)
5-20MB:    24 (9%)
> 20MB:      9 (4%) ← 這 9 個就佔了大半空間
```

### JSONL 事件結構

最大 session（55MB）的組成：
- `user` 事件佔 48.2 MB (89%) — base64 截圖、大量貼入內容、tool results
- `progress` 佔 3.1 MB — hook/agent 進度
- `assistant` 佔 2.5 MB — 回應
- `file-history-snapshot` + 其他 < 1 MB

事件類型：`progress`, `file-history-snapshot`, `user`, `assistant`, `system`, `queue-operation`

## File Structure

```
~/workshop/stations/session-archiver/
├── SPEC.md                           # 本文件
├── pyproject.toml                    # uv project
├── __main__.py                       # CLI 入口（COMMANDS dispatch，仿 system-monitor）
├── src/session_archiver/
│   ├── __init__.py
│   ├── config.py                     # Settings — JSON config + env override（仿 system-monitor）
│   ├── db.py                         # Schema DDL + CRUD — psycopg3 直連 PG
│   ├── models.py                     # Pydantic models: SessionMeta, ScoreBreakdown, ArchiveRecord
│   ├── scanner.py                    # 掃描 ~/.claude/projects/ 收集 session metadata
│   ├── scorer.py                     # 四維評分引擎
│   ├── archiver.py                   # zstd 壓縮 + stub 生成 + DB 寫入
│   ├── thaw.py                       # 解壓還原
│   ├── summarizer.py                 # LLM 摘要生成（claude --model haiku -p）
│   └── cli.py                        # 子命令實作：scan / score / archive / thaw / status / search
├── scripts/
│   └── run-archiver.sh               # launchd wrapper（雙層 fallback）
└── launchd/
    └── com.joneshong.session-archiver.plist
```

## Workshop 共享模組（可複用）

| 模組 | 路徑 | 用途 |
|------|------|------|
| **Embedding** | `core/src/shared/embedding.py` | Ollama nomic-embed-text 768d 向量，`get_embedding()` / `get_embeddings_batch()` — 降級回 None |
| **S3 Storage** | `core/src/shared/storage.py` | aiobotocore S3 client，`upload_blob()` / `resolve_content()` — 降級回 None |
| **DB Pattern** | `core/src/shared/database.py` | SQLAlchemy async + psycopg3，`create_async_engine()` |
| **Config Pattern** | `stations/system-monitor/config.json` | JSON config + env override，data dir `~/.claude/data/<name>/` |
| **Scheduler** | `schedules/sync.sh` | launchd plist install/uninstall/status |
| **Shell Wrapper** | `stations/system-monitor/scripts/` | 雙層 fallback（API → offline CLI） |

> **Note**: `corelib.db` 已完全棄用。所有 Workshop 服務已遷移至 SQLAlchemy async。
> Session Archiver 作為獨立 station，不 import Core 模組，但複用相同 pattern。
> DB 連線用 psycopg3 直連（非 async），因 station 是 CLI 工具非 FastAPI 服務。

## PostgreSQL Schema (`workshop_session_archive`)

對齊 Workshop Core 的 archive 表模式（B-tree/GIN，無 HNSW）：

```sql
-- Table 1: Session index + archive metadata
CREATE TABLE IF NOT EXISTS sessions (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL UNIQUE,       -- UUID from JSONL
    project_path    TEXT NOT NULL,              -- e.g. "-Users-joneshong-workshop"
    tier            TEXT NOT NULL DEFAULT 'hot', -- hot / cold / frozen

    -- Raw metadata (from scan)
    file_size_bytes BIGINT NOT NULL DEFAULT 0,
    event_count     INTEGER NOT NULL DEFAULT 0,
    turn_count      INTEGER NOT NULL DEFAULT 0,  -- count of 'user' events
    has_companion   BOOLEAN NOT NULL DEFAULT FALSE,
    companion_size  BIGINT NOT NULL DEFAULT 0,
    first_timestamp TEXT,
    last_timestamp  TEXT,
    claude_version  TEXT,
    git_branch      TEXT,
    cwd             TEXT,

    -- Score
    score           DOUBLE PRECISION NOT NULL DEFAULT 0,
    score_size      DOUBLE PRECISION NOT NULL DEFAULT 0,
    score_age       DOUBLE PRECISION NOT NULL DEFAULT 0,
    score_activity  DOUBLE PRECISION NOT NULL DEFAULT 0,
    score_compress  DOUBLE PRECISION NOT NULL DEFAULT 0,

    -- Archive info (NULL if not yet archived)
    archive_path    TEXT,                       -- local path or s3:// URI
    archive_type    TEXT,                       -- 'cold-archive' | 'cold-blob' (對齊 Core 命名)
    compressed_size BIGINT,
    compression_ratio DOUBLE PRECISION,
    archived_at     TEXT,
    thawed_at       TEXT,                       -- last thaw timestamp
    thaw_count      INTEGER NOT NULL DEFAULT 0,

    -- Summary
    summary         TEXT,                       -- LLM-generated one-liner

    -- Housekeeping
    scanned_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Embedding 分離至子表（對齊 Core 的 Phase 2 embedding subtable 模式）
CREATE TABLE IF NOT EXISTS session_embeddings (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL UNIQUE REFERENCES sessions(session_id) ON DELETE CASCADE,
    embedding       VECTOR(768) NOT NULL        -- nomic-embed-text summary embedding
);

CREATE INDEX IF NOT EXISTS idx_sessions_tier ON sessions(tier);
CREATE INDEX IF NOT EXISTS idx_sessions_score ON sessions(score DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path);
CREATE INDEX IF NOT EXISTS idx_sessions_last_ts ON sessions(last_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_archive_type ON sessions(archive_type);
CREATE INDEX IF NOT EXISTS idx_se_embedding ON session_embeddings
    USING hnsw (embedding vector_cosine_ops);

-- Table 2: Archive operations log (audit trail)
CREATE TABLE IF NOT EXISTS archive_log (
    id          SERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL,
    action      TEXT NOT NULL,  -- 'archive', 'thaw', 'freeze', 'migrate'
    from_tier   TEXT,
    to_tier     TEXT,
    details     TEXT,           -- JSON string (dedup_hash for idempotency, 對齊 P2 冪等模式)
    dedup_hash  TEXT UNIQUE,    -- SHA256(session_id + action + timestamp) — ON CONFLICT DO NOTHING
    created_at  TEXT NOT NULL
);
```

> **變更說明**:
> - `tier` 值簡化：`hot` / `cold` / `frozen`（移除 `warm`）
> - 新增 `archive_type`：對齊 Core 的 `cold-archive` / `cold-blob` 命名
> - Embedding 分離至 `session_embeddings` 子表（對齊 Core Phase 2 模式 `block_embeddings`）
> - `archive_log` 加入 `dedup_hash`（對齊 P2 冪等投影模式，crash-safe）

## Tiering System

對齊 Workshop Core 的冷熱分層命名慣例（HOT / COLD-ARCHIVE / COLD-BLOB）：

```
┌──────────────────────────────────────────────────────────────┐
│  HOT  ← 不動                                                │
│  條件：最近 3 天 OR 當前活躍 session                          │
│  位置：~/.claude/projects/ (原地)                             │
│  索引：DB 有 metadata row，但不壓縮                           │
├──────────────────────────────────────────────────────────────┤
│  COLD-ARCHIVE  ← 壓縮 + 保留 metadata stub                  │
│  條件：評分 > threshold 且 age > 3d                           │
│  位置：~/.claude/archive/cold/*.jsonl.zst                    │
│  索引：DB 有 metadata row + summary embedding（pgvector）    │
│  搜尋：summary 語意搜尋 + metadata ILIKE fallback            │
├──────────────────────────────────────────────────────────────┤
│  COLD-BLOB  ← S3 遠端備份（未來 Phase 2）                   │
│  條件：COLD-ARCHIVE 超過 90 天未被 thaw                      │
│  位置：s3://workshop-archive/sessions/*.jsonl.zst            │
│  本機保留 metadata stub，壓縮檔移至 S3                        │
│  使用 core/src/shared/storage.py 的 upload_blob()            │
└──────────────────────────────────────────────────────────────┘
```

> **設計決策**: WARM tier 移除。原本 WARM 只是「建索引不壓縮」，實際上 scan 已對所有 session 建索引，
> 壓不壓由 score threshold 決定，不需要額外 tier 狀態。簡化為 `hot` → `cold` 二態 + 未來 `frozen`。

## Scoring Algorithm (`scorer.py`)

四維加權評分模型（0-100），分數越高越適合壓縮歸檔：

```python
def score_session(meta: SessionMeta) -> ScoreBreakdown:
    """Four-factor weighted score (0-100). Higher = more suitable for archiving."""

    # 1. Size (weight: 30, range: 0-30)
    #    Sigmoid curve: <100KB → ~0, 1MB → ~8, 10MB → ~22, 50MB → ~28
    size_mb = meta.file_size_bytes / (1024 * 1024)
    s_size = 30 * (1 - math.exp(-size_mb / 10))

    # 2. Age (weight: 25, range: 0-25)
    #    Exponential decay: 0 days → 0, 3 days → ~5, 7 days → ~12, 30 days → ~23
    age_days = (now - meta.last_modified).days
    s_age = 25 * (1 - math.exp(-age_days / 10))

    # 3. Activity — INVERSE (weight: 25, range: 0-25)
    #    More active = LOWER score (less suitable for archiving)
    #    Factors: has_companion (was resumed), turn_count, thaw_count
    activity_raw = (
        (10 if not meta.has_companion else 0) +   # never resumed → +10
        max(0, 15 - meta.turn_count * 0.5)         # fewer turns → higher
    )
    s_activity = min(25, activity_raw)

    # 4. Compressibility (weight: 20, range: 0-20)
    #    Estimate from user event ratio (base64 screenshots compress well)
    user_ratio = meta.user_event_bytes / max(meta.file_size_bytes, 1)
    s_compress = 20 * user_ratio  # user events are ~89% of big sessions

    return ScoreBreakdown(
        total=s_size + s_age + s_activity + s_compress,
        size=s_size, age=s_age, activity=s_activity, compressibility=s_compress,
    )
```

### Score Examples (預估)

| Session | Size | Age | Resumed | Score | Action |
|---------|------|-----|---------|-------|--------|
| 55MB, 10d old, never resumed | 28 | 16 | 25 | ~85 | COLD（壓縮） |
| 30MB, 5d old, resumed 3x | 25 | 10 | 5 | ~55 | HOT（未達閾值 70） |
| 200KB, 20d old, never resumed | 1 | 22 | 25 | ~52 | HOT（太小不值得壓） |
| 2MB, 1d old, active | 5 | 2 | 5 | ~18 | HOT |

## Archive Workflow

```
scan → score → filter(score > threshold AND tier == 'hot' AND age > 3d) → archive
```

Per session:
1. **Scan**: Parse JSONL header (first + last event) → extract metadata
2. **Score**: Apply 4-factor model
3. **Summarize**: `claude --model haiku -p "Summarize this session in 1 sentence: {first_user_msg + last_user_msg}"` (skip if summary already exists)
4. **Embed**: 呼叫 Ollama nomic-embed-text API（`POST localhost:11434/api/embed`）→ 存入 `session_embeddings`
   - 降級：Ollama 不可用時跳過 embedding，summary 仍存入 sessions 表供 ILIKE 搜尋
   - 對齊 `core/src/shared/embedding.py` 的 graceful degradation pattern
5. **Compress**: `zstd -9 session.jsonl -o ~/.claude/archive/cold/{session_id}.jsonl.zst`
6. **Companion**: If companion dir exists, `tar cf - {dir} | zstd -9 > {session_id}.companion.tar.zst`
7. **Verify**: `zstd -t` on compressed file (integrity check)
8. **Stub**: Write `{session_id}.archived.json` to original location (metadata for search)
9. **DB**: INSERT/UPDATE sessions table + INSERT archive_log（with `dedup_hash`，P2 冪等）
10. **Remove**: Delete original JSONL + companion dir only after verify passes

### Graceful Degradation（對齊 Workshop 韌性模式）

| 依賴 | 不可用時 | 行為 |
|------|---------|------|
| PostgreSQL | DB 離線 | scan/archive 跳過 DB 寫入，只做本機壓縮 + stub；下次 PG 恢復時 scan 重建索引 |
| Ollama | Embedding 服務掛 | 跳過 embedding 生成，summary 仍寫入 DB；搜尋降級為 ILIKE |
| zstd | 罕見 | CLI 工具缺失 → 報錯退出（不降級，壓縮是核心功能） |

> **變更**：移除 SQLite fallback 設計。Workshop 已棄用 corelib 的 PG/SQLite 雙軌，
> 改為統一 PostgreSQL + graceful degradation（返回 None / 跳過）。
> Session Archiver 的核心價值是壓縮檔案，DB 只是索引，離線時本機壓縮仍能運作。

## Thaw Workflow (`thaw.py`)

```bash
session-archiver thaw <session_id>
```

1. Look up `archive_path` in DB (or read local stub)
2. `zstd -d {archive_path} -o ~/.claude/projects/{project}/{session_id}.jsonl`
3. If companion archive exists → `zstd -d | tar xf -`
4. Update DB: `tier='hot'`, `thawed_at=now`, `thaw_count += 1`
5. Remove `.archived.json` stub
6. Log to `archive_log`
7. Print: `Session {id} restored. Use: claude --resume {id}`

## Metadata Stub Format

```json
{
  "_type": "archived-session",
  "sessionId": "0b65102b-...",
  "tier": "cold",
  "archiveType": "cold-archive",
  "archivedAt": "2026-02-26T12:00:00Z",
  "originalSize": 57671680,
  "compressedSize": 4821043,
  "compressionRatio": 0.916,
  "archivePath": "~/.claude/archive/cold/0b65102b-....jsonl.zst",
  "summary": "Workshop 設定大改造，80 skills 整合",
  "firstTimestamp": "2026-02-16T02:00:00Z",
  "lastTimestamp": "2026-02-16T10:04:00Z",
  "eventCount": 4274,
  "turnCount": 881,
  "score": 78.3,
  "thawCommand": "session-archiver thaw 0b65102b"
}
```

## CLI Commands

```bash
# 仿 stations/system-monitor 的 COMMANDS dispatch 模式
# 入口：uv run python -m session_archiver <command>

session-archiver scan              # 掃描所有 sessions，更新 DB index
session-archiver score             # 顯示所有 session 評分（table 格式）
session-archiver score --top 20    # 只看前 20 高分
session-archiver archive           # 執行壓縮（score > threshold 且 age > 3d）（dry-run 預設）
session-archiver archive --execute # 實際執行壓縮（對齊 archive_cold_data.py 模式）
session-archiver archive --threshold 50  # 自訂閾值（預設 70）
session-archiver thaw <session_id> # 解壓還原
session-archiver status            # 各 tier 統計 + 空間節省量
session-archiver search "keyword"  # 搜尋 summary（pgvector 語意 → ILIKE fallback）
```

> **變更**：`--dry-run` 改為預設行為，需 `--execute` 才實際壓縮（對齊 `scripts/archive_cold_data.py` 的安全設計）。

## run-archiver.sh — 雙層 Fallback

仿 `stations/system-monitor/scripts/` 模式：

```
Route 1 (API): curl -sf POST gateway:8800/api/session-archive/run
Route 2 (Offline): 直接呼叫 python CLI
  - uv run python -m session_archiver scan
  - uv run python -m session_archiver archive
```

Offline 模式下 DB 寫入自動跳過（graceful degradation），壓縮 + stub 仍正常執行。
下次 PG 恢復時 `scan` 命令會重新掃描所有 session（含 archived stub），重建完整索引。

## launchd Plist

```xml
<!-- com.joneshong.session-archiver.plist -->
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.joneshong.session-archiver</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/joneshong/workshop/stations/session-archiver/scripts/run-archiver.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>5</integer>
        <key>Minute</key><integer>15</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/joneshong/.claude/data/session-archiver/launchd-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/joneshong/.claude/data/session-archiver/launchd-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/Users/joneshong/.local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

排程 05:15 — disk-report 05:00 完成後 15 分鐘再跑，避免同時 I/O。

## disk-report 整合

在 `collect-disk-data.sh` 或報告 prompt 中加入 archive status 區塊：

```bash
# Collect archive stats
if command -v session-archiver &>/dev/null; then
  session-archiver status --json >> "$DATA_FILE"
fi
```

報告模板增加：
```
## Session Archive Status
- Hot: {n} sessions ({size})
- Cold (本機): {n} sessions (原 {orig} → 壓縮後 {compressed})
- Frozen (S3): {n} sessions
- 今日壓縮: {n} sessions, 節省 {saved}
- 累計節省: {total_saved} ({pct}%)
```

## Implementation Order

1. **Project scaffold** — `pyproject.toml` + `__main__.py` + package structure（仿 system-monitor）
2. **config.py** — JSON config loader + env override（`~/.claude/data/session-archiver/config.json`）
3. **scanner.py** — JSONL metadata extraction（parse first/last lines + stat）
4. **scorer.py** — 四維評分引擎
5. **db.py** — PostgreSQL schema DDL + CRUD（psycopg3 直連，graceful degradation）
6. **archiver.py** — zstd 壓縮 + stub 生成 + companion handling
7. **thaw.py** — 解壓還原
8. **summarizer.py** — LLM 摘要（claude --model haiku -p）
9. **embedding.py** — Ollama nomic-embed-text 768d（複用 `core/src/shared/embedding.py` pattern）
10. **cli.py** — 子命令實作（scan/score/archive/thaw/status/search）
11. **`__main__.py`** — COMMANDS dispatch 入口
12. **run-archiver.sh** — 雙層 fallback shell script
13. **launchd plist** — 排程配置（05:15）
14. **disk-report 整合** — 加入 archive status 區塊
15. **真實測試** — 挑 3 個高分 session 實際壓縮 → thaw → resume 驗證

## Verification

1. **Scan accuracy**: `session-archiver scan` → 確認所有 sessions 被掃到，metadata 正確
2. **Score sanity**: `session-archiver score --top 10` → 最大最舊的 session 分數最高
3. **Dry run**: `session-archiver archive --dry-run` → 確認只選到合理的候選
4. **Real archive**: 挑一個 >20MB 的 session 壓縮 → 確認 `.zst` 存在、stub 存在、原檔已移除
5. **Compression ratio**: 預期 85-95%，55MB → ~5MB
6. **Thaw round-trip**: `session-archiver thaw <id>` → `claude --resume <id>` 能正常載入
7. **Semantic search**: `session-archiver search "skills"` → 能找到相關 session（via pgvector）
8. **ILIKE fallback**: 停 Ollama → 搜尋降級為 ILIKE，仍回傳結果
9. **PG offline**: 停 PG → 跑 archiver → 確認本機壓縮 + stub 正常產出（DB 寫入跳過）
10. **PG recovery**: 重啟 PG → `scan` → 確認從 stub 重建索引
11. **Idempotency**: 重複執行 archive → `dedup_hash` ON CONFLICT DO NOTHING，不重複寫入
12. **disk-report**: 確認日報多了 Archive Status 區塊

## Dependencies

- **Depends on**: PostgreSQL 16 + pgvector、Ollama nomic-embed-text（可降級）、zstd CLI
- **Integrates with**: disk-report 日報、Workshop Gateway API
- **Reuses patterns from**: `core/src/shared/embedding.py`（embedding）、`core/src/shared/storage.py`（S3, future）
- **No longer depends on**: ~~`corelib.db`~~（已棄用）

## Resilience Alignment（對齊 Workshop AD-10 事件韌性模式）

| 韌性模式 | Session Archiver 應用 |
|---------|----------------------|
| **P1 事件時效分類** | archive_log 記錄有 `created_at`，replay 時可判斷是否過期 |
| **P2 冪等投影** | `dedup_hash = SHA256(session_id + action + ts)` → `ON CONFLICT DO NOTHING` |
| **P3 WAL-Projection 分離** | 本機 `.zst` + `.archived.json` stub 是 ground truth，DB 只是投影 |
| **P5 非阻塞隔離** | archive 操作失敗不阻塞其他 session 的處理，每個 session 獨立 try/except |
| **P6 層級式過載保護** | `--threshold` 可動態調整壓縮量，避免一次壓太多 I/O |
