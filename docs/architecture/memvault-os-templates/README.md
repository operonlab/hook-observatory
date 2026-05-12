# memvault-os Templates

這個目錄存放 **memvault-os 開源發行版** 所需的 adapter shim 與部署 bundle template。

根據 [distribution-pattern.md](../distribution-pattern.md) 的設計，workshop 是上游事實源，
`joneshong/memvault-os` 是下游發行版。本目錄的檔案在 subtree split 後複製到下游 repo。

---

## 目錄結構

```
memvault-os-templates/
├── README.md                   # 這份文件
├── adapter/
│   ├── auth_standalone.py      # 取代 workshop auth（單 token、無 Redis session）
│   └── eventbus_inmem.py       # 取代 Redis Streams（in-process asyncio.Queue）
├── deploy/
│   ├── docker-compose.yml      # PG + Redis + memvault-os 一起起
│   ├── .env.example            # 所有必要 env var 說明
│   └── bootstrap.sql           # 建表 SQL（取代 Alembic）
└── scripts/
    └── sync-from-workshop.sh   # subtree split 同步工具
```

---

## 什麼時候需要這些 template

**情境**：你要把 `joneshong/memvault-os` 開源 repo 的程式碼從 workshop 同步出來，
或是第一次建立 memvault-os 的可執行環境時。

### adapter/ — 在下游 repo 放入 drop-in 替換

下游開源使用者沒有 workshop 的：
- `core/src/modules/auth/` (itsdangerous + Redis session)
- `core/src/events/` (Redis Streams cross-module event bus)

這兩個 adapter 用最小相依（Python stdlib + FastAPI）重新實作相同的 signature，
讓 memvault core 程式碼不需要改動就能在 standalone 環境跑。

**使用方式（下游 repo）**：

```
memvault-os/
├── adapter/
│   ├── auth_standalone.py   ← 從這裡 copy 進來
│   └── eventbus_inmem.py    ← 從這裡 copy 進來
├── core/                    ← subtree split 同步進來
└── ...
```

在下游 `main.py` 裡：

```python
# 取代 workshop auth
from adapter.auth_standalone import get_current_user

# 取代 workshop event bus
from adapter.eventbus_inmem import InMemEventBus
event_bus = InMemEventBus()
```

### deploy/ — 下游 repo 自帶部署環境

下游使用者執行：

```bash
cp deploy/.env.example .env
# 編輯 .env，填入 MEMVAULT_OS_TOKEN 等必要值

docker compose -f deploy/docker-compose.yml up -d
# 等 PG/Redis 起動後
docker compose exec memvault-os psql -U memvault -d memvault_db -f /app/bootstrap.sql
```

### scripts/sync-from-workshop.sh — 少爺（維護者）同步用

每次 workshop 主版有改動需要推到下游時執行：

```bash
export MEMVAULT_OS_REMOTE=https://github.com/joneshong/memvault-os
./scripts/sync-from-workshop.sh
```

---

## Known Limitations

### bootstrap.sql

- **不含 pgvector extension**：embedding 向量欄位 (`embedding vector(1024)`) 需要先安裝 `pgvector`。
  `bootstrap.sql` 已包含 `CREATE EXTENSION IF NOT EXISTS vector;`，但如果 PG image
  沒有預裝 pgvector（`pgvector/pgvector:pg16` 有內建），需要手動安裝。
- **不含完整 index**：省略了 HNSW vector index（`CREATE INDEX ... USING hnsw ...`），
  因為建立 HNSW index 需要 pgvector 並且費時。小規模部署（< 10,000 筆）走 sequential scan 可接受。
  生產部署應自行補上：
  ```sql
  CREATE INDEX idx_blocks_embedding_hnsw ON memvault.blocks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
  ```
- **BlockFrozen / BlockArchive 的 S3 欄位**：這些 table 在 workshop 搭配 RustFS (S3-compatible)。
  standalone 環境如果沒有 S3，`blocks_frozen.s3_uri` 欄位會存空字串或留 NULL，
  冷封存功能不可用。

### auth_standalone.py

- 只支援**單一管理員 token**（env var `MEMVAULT_OS_TOKEN`）。
- 無 multi-user / RBAC / Space 權限系統。
- `User.id` 固定回傳 `"standalone-admin"`，`User.space_id` 固定回傳 `"default"`。

### eventbus_inmem.py

- **重啟即清空**：in-process Queue，程序重啟後 pending events 消失。
- **無 consumer group**：沒有 at-least-once 保證，handler 如果拋例外 event 不重試。
- **無跨進程**：適合單一 process 內部，不支援 scale-out。
