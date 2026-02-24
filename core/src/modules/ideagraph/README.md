# ideagraph — 靈感孵化與知識圖譜模組

> AI 輔助的想法孵化系統——忠實記錄零碎混亂的靈感，自動語意修正、推演連結，等待人類驗證後固化為知識圖譜。

## 定位

| 屬性 | 值 |
|------|-----|
| **Schema** | `ideagraph` |
| **依賴** | auth |
| **被依賴於** | intelflow（情報→靈感轉入） |
| **MCP** | `workshop-ideagraph`（CRUD ~8 tools）+ `workshop-ideagraph-ai`（AI 輔助 ~5 tools） |
| **V1 參考** | `pulso-muse` MCP（8 tools） |

## 核心工作流：Capture → Refine → Connect → Verify

```
少爺的零碎描述
    │
    ▼
1. Capture（原始捕捉）   → raw_content 保留原文（不可變）
    │
    ▼
2. Refine（語意精煉）    → AI 產生 refined_content + summary + tags
    │
    ▼
3. Connect（推演連結）   → pgvector 語意比對 → suggested_links
    │
    ▼
4. Verify（人類驗證）    → 確認/拒絕/調整 suggested_links
```

**關鍵原則**：
- **永遠保留原文**：raw_content 不可變，refined 是衍生版本
- **AI 建議，人類決定**：所有自動連結都是 `suggested` 狀態，需人類 verify
- **漸進式清晰**：Spark 可以從模糊開始，隨時間被多次精煉

## DB Schema

```sql
CREATE SCHEMA ideagraph;

ideagraph.sparks        -- 靈感節點（raw_content, refined_content, title, summary, type, tags[], embedding, status, x/y）
ideagraph.links         -- 連結邊（source_id, target_id, type, weight, status: suggested/verified/rejected）
ideagraph.refinements   -- 精煉歷史（spark_id, version, content, diff_note, refined_by）
```

所有資料表含 `space_id` 和 `created_by`。

### Spark 類型

| type | 說明 | Galaxy 顏色 |
|------|------|------------|
| concept | 概念 | 藍 |
| project | 專案 | 綠 |
| idea | 想法 | 金 |
| question | 問題 | 紫 |
| resource | 資源 | 白 |
| observation | 觀察 | 橙 |

### Link 類型

`causes` / `enables` / `supports` / `contradicts` / `extends` / `inspires`

## API 端點

| 方法 | 路徑 | 用途 |
|------|------|------|
| POST | `/api/ideagraph/sparks` | 捕捉新 Spark（自動觸發 refine pipeline） |
| GET | `/api/ideagraph/sparks` | Spark 列表（過濾：type/tags/status） |
| GET | `/api/ideagraph/sparks/{id}` | Spark 詳情（含 raw/refined 對照、連結、精煉歷史） |
| PUT | `/api/ideagraph/sparks/{id}` | 手動更新 Spark |
| DELETE | `/api/ideagraph/sparks/{id}` | 刪除 Spark |
| POST | `/api/ideagraph/sparks/{id}/refine` | AI 精煉指定 Spark |
| POST | `/api/ideagraph/sparks/{id}/suggest-links` | AI 推演潛在連結 |
| POST | `/api/ideagraph/links` | 手動建立連結（status=verified） |
| DELETE | `/api/ideagraph/links/{id}` | 刪除連結 |
| POST | `/api/ideagraph/links/{id}/verify` | 驗證 suggested link |
| POST | `/api/ideagraph/links/batch-verify` | 批量驗證 |
| GET | `/api/ideagraph/graph` | 取得圖譜（支援 filter） |
| POST | `/api/ideagraph/search` | pgvector 語意搜尋 |

## 目錄結構

```
core/src/modules/ideagraph/
├── __init__.py
├── routes.py           # 所有 API 端點
├── models.py           # sparks, links, refinements
├── schemas.py          # Pydantic request/response
├── services.py         # 公開 API（Spark CRUD、精煉、連結管理）
├── events.py           # ideagraph.spark.captured, ideagraph.link.verified 等
├── deps.py             # 權限驗證
├── pipeline.py         # Capture→Refine→Connect 自動管線
└── embedding.py        # pgvector embedding 產生（OpenAI / Ollama）
```

## 事件

| 事件 | 觸發時機 |
|------|---------|
| `ideagraph.spark.captured` | 新 Spark 被捕捉 |
| `ideagraph.spark.refined` | Spark 被精煉 |
| `ideagraph.link.suggested` | AI 建議新連結 |
| `ideagraph.link.verified` | 連結被確認 |
| `ideagraph.link.rejected` | 連結被拒絕 |

## 跨模組整合

- **memvault**：記憶中的想法可轉入為 Spark（`memvault.block.created` → 可選轉入）
- **finance**：消費相關想法轉入（`finance.transaction.created` → 可選轉入）
- **taskflow**：完成任務時的新點子轉入（`taskflow.task.completed` → 可選轉入）

## 參考文件

- [P7 藍圖](../../docs/blueprint/p7-ideagraph.md) — 完整 DB schema + MCP tools + Galaxy UI 設計
- [服務目錄](../../docs/vision/domain-catalog.md) — ideagraph 定位
