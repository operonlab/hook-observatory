# Feature Lifecycle: POC → Production

## Decision Tree

```
新想法到來
    │
    ├─ 沒把握 / 需要驗證 → lab/<name>-poc/
    │
    └─ 確定要做 / 規格明確 → 直接 services/<name>/
```

## Phases

### Phase 1: Explore (lab/)

```
lab/<name>-poc/
├── README.md      ← 寫下：目標、假設、成功標準
├── outputs/       ← Skill 產出 .md / .json
└── scripts/       ← 快速驗證腳本
```

- Skill 輸出路徑：`~/workshop/lab/<name>-poc/outputs/`
- 格式：.md（方便閱讀、快速迭代）
- 不需要 pyproject.toml、不需要 tests/、不需要遵守正式結構
- README.md 持續更新觀察與發現

### Phase 2: Validate

- 根據成功標準評估 POC 結果
- 在 README.md 記錄結論

**如果失敗**：
```
lab/<name>-poc/README.md  ← 補上「為什麼失敗」「學到什麼」
lab/<name>-poc/outputs/   ← 刪除（或保留有價值的）
```
失敗紀錄有價值 — 避免未來重複踩坑。

### Phase 3: Graduate 🎓

**如果成功 → 正式化**：

1. 建立正式服務骨架：
   ```bash
   mkdir -p services/<name>/{src/<name>/{routes,models,core},tests,migrations}
   ```

2. 建立正式前端（如需要）：
   ```bash
   mkdir -p apps/<name>/{src/{components,pages,hooks},public}
   ```

3. 寫遷移腳本（.md → DB）：
   ```
   lab/<name>-poc/scripts/migrate-to-db.py
   ```

4. 匯入資料並驗證

5. 更新 lab README.md：
   ```markdown
   ## Status: GRADUATED
   Migrated to services/<name>/ + apps/<name>/ on YYYY-MM-DD
   ```

### Phase 4: Cleanup

| 狀態 | 處理 |
|------|------|
| 畢業 | 保留 README.md，刪除 outputs/ |
| 失敗 | 保留 README.md，刪除其餘 |
| 閒置 > 30 天 | 提醒決定：保留 or 清理 |

## Skill Output Path Convention

| 階段 | 輸出路徑 | 格式 |
|------|---------|------|
| POC | `~/workshop/lab/<name>-poc/outputs/` | .md / .json |
| Production | HTTP API → PostgreSQL | DB records |

## Rules

1. `services/` 和 `apps/` **絕對不會有 .md 產出物** — 只有程式碼
2. `lab/` 的東西**不會被**任何正式服務 import
3. 每個 POC 都有 README.md — 即使失敗也記錄
4. POC 命名：`<domain>-poc`（跟 services/ 裡的正式名稱加後綴區分）
