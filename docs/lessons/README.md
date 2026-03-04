---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

# 實戰教訓

> 從專案開發中提煉的經驗與模式。每份文件記錄一次重要的問題排除或設計修正。

| 文件 | 主題 | 核心教訓 |
|------|------|---------|
| [frontend-color-system-fix.md](./frontend-color-system-fix.md) | 前端色彩系統修復 | CSS 變數覆蓋 + Tailwind 自定義色彩的正確方式 |
| [hook-observatory-resilience.md](./hook-observatory-resilience.md) | Hook Observatory 韌性 | WAL-Projection 分離、Checkpoint Recovery（→ AD-10） |

## 撰寫指南

新增教訓文件時，遵循以下結構：

```markdown
# {問題標題}

## 問題描述
發生了什麼？影響範圍？

## 根本原因
為什麼會發生？

## 解決方案
怎麼修的？

## 教訓
可推廣的通用結論是什麼？
```

如果教訓具有架構級的通用性，應提煉為 [event-resilience-patterns.md](../architecture/event-resilience-patterns.md) 或新的 ADR。
