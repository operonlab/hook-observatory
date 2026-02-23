---
doc_version: 2
content_hash: 610be881
source_version: 2
target_lang: zh-TW
translated_at: 2026-02-23
---

# 功能生命週期：POC → Production

## 決策樹

```
新想法到來
    │
    ├─ 不確定 / 需要驗證 → lab/<name>-poc/
    │
    └─ 已確認 / 規格明確 → 直接進入 services/<name>/
```

## 階段

### 階段 1：探索 (lab/)

```
lab/<name>-poc/
├── README.md      ← 文件：目標、假設、成功標準
├── outputs/       ← Skill 輸出 (.md / .json)
└── scripts/       ← 快速驗證腳本
```

- Skill 輸出路徑：`~/workshop/lab/<name>-poc/outputs/`
- 格式：.md (易讀、快速迭代)
- 不需要 pyproject.toml、tests/ 或正式結構
- README.md 持續更新觀察與發現

### 階段 2：驗證

- 根據成功標準評估 POC 結果
- 將結論記錄在 README.md

**如果失敗**：
```
lab/<name>-poc/README.md  ← 添加「失敗原因」與「經驗教訓」
lab/<name>-poc/outputs/   ← 刪除 (或保留有價值的產出)
```
失敗記錄非常有價值 —— 它們能防止重複犯錯。

### 階段 3：晉升 (Graduate)

**如果成功 → 正式化**：

1. 建立正式服務骨架：
   ```bash
   mkdir -p services/<name>/{src/<name>/{routes,models,core},tests,migrations}
   ```

2. 建立正式前端 (如果需要)：
   ```bash
   mkdir -p apps/<name>/{src/{components,pages,hooks},public}
   ```

3. 撰寫遷移腳本 (.md → DB)：
   ```
   lab/<name>-poc/scripts/migrate-to-db.py
   ```

4. 匯入數據並驗證

5. 更新 lab README.md：
   ```markdown
   ## Status: GRADUATED
   已於 YYYY-MM-DD 遷移至 services/<name>/ + apps/<name>/
   ```

### 階段 4：清理

| 狀態 | 行動 |
|--------|--------|
| 已晉升 | 保留 README.md，刪除 outputs/ |
| 已失敗 | 保留 README.md，刪除其餘內容 |
| 閒置 > 30 天 | 提示進行決策：保留或清理 |

## Skill 輸出路徑規範

| 階段 | 輸出路徑 | 格式 |
|-------|------------|--------|
| POC | `~/workshop/lab/<name>-poc/outputs/` | .md / .json |
| Production | HTTP API → PostgreSQL | 資料庫記錄 |

## 規則

1. `services/` 與 `apps/` **絕不包含 .md 產出物** —— 僅限程式碼
2. `lab/` 中的任何內容**絕不會被正式服務引用 (imported)**
3. 每個 POC 都有 README.md —— 即使是失敗的嘗試也會被記錄
4. POC 命名：`<domain>-poc` (透過後綴與正式服務名稱區隔)
