# ideagraph — 靈感孵化 UI

> Galaxy 風格知識圖譜視覺化 + 想法捕捉/精煉/驗證互動介面。

## 路由

| 路徑 | 頁面 | 說明 |
|------|------|------|
| `/ideagraph` | Galaxy | 知識圖譜主畫面（D3 force-directed） |
| `/ideagraph/sparks` | SparkList | Spark 列表（過濾：type/tags/status） |
| `/ideagraph/sparks/new` | CaptureForm | 快速捕捉想法 |
| `/ideagraph/sparks/:id` | SparkDetail | Spark 詳情（raw/refined 對照 + 精煉歷史 + 連結） |
| `/ideagraph/verify` | VerifyQueue | 待驗證 suggested links 佇列 |
| `/ideagraph/search` | SemanticSearch | pgvector 語意搜尋 |

## Galaxy 視覺化設計

| 元素 | 對應 | 說明 |
|------|------|------|
| 星星 | Spark | 每個 Spark 一顆星 |
| 星星大小 | 連結數量 | 越多越大 |
| 星星顏色 | type | concept=藍、project=綠、idea=金、question=紫 |
| 星星亮度 | status | draft=暗淡、refined=正常、verified links 多=明亮 |
| 虛線 | suggested link | 脈動動畫，待驗證 |
| 實線 | verified link | 已確認的連結 |
| 拖曳 | 座標調整 | 拖曳 Spark 重新排列，座標寫回 DB |

## 元件

```
workbench/src/modules/ideagraph/
├── pages/
│   ├── Galaxy.tsx              # D3 force-directed 主畫面
│   ├── SparkList.tsx           # Spark 列表
│   ├── CaptureForm.tsx         # 快速捕捉
│   ├── SparkDetail.tsx         # Spark 詳情（raw/refined 對照）
│   ├── VerifyQueue.tsx         # 批量驗證 suggested links
│   └── SemanticSearch.tsx      # 語意搜尋
├── components/
│   ├── graph/
│   │   ├── ForceGraph.tsx      # D3 force simulation 核心
│   │   ├── SparkNode.tsx       # 星星節點渲染
│   │   ├── LinkEdge.tsx        # 連結線渲染（虛線/實線）
│   │   └── GraphControls.tsx   # 縮放/過濾/佈局控制
│   ├── SparkCard.tsx           # Spark 摘要卡片
│   ├── RawRefinedDiff.tsx      # 原始 vs 精煉對照
│   ├── RefinementHistory.tsx   # 精煉版本歷史
│   ├── LinkVerifyCard.tsx      # 單條連結驗證卡片
│   └── CaptureQuickInput.tsx   # Ctrl+Shift+I 快捷輸入
├── hooks/
│   ├── useSparks.ts
│   ├── useGraph.ts
│   └── useVerify.ts
├── stores/
│   └── ideagraphStore.ts       # Zustand
├── api/
│   └── ideagraphApi.ts
└── index.tsx
```

## 技術選型

| 層面 | 方案 |
|------|------|
| 圖譜渲染 | **D3.js force-directed graph**（2D，效能好、生態成熟） |
| 3D 備選 | Three.js（若未來需要 3D Galaxy 體驗） |
| 拖曳互動 | D3 drag behavior |
| 佈局演算法 | Force simulation + 手動座標覆蓋 |
| 響應式 | canvas 自適應容器，行動端 touch 拖曳 |

## 互動功能

1. **Capture 快捷鍵**：`Ctrl+Shift+I` → 彈出輸入框 → 直接 capture
2. **點擊 Spark**：展開詳情面板（raw→refined 對照、連結清單、精煉歷史）
3. **Hover Link**：顯示連結類型、AI 建議理由
4. **右鍵 Spark**：Refine / Archive / Delete
5. **Verify 模式**：逐一審視 suggested links（Accept / Reject / Edit）
6. **Filter**：按 type、tags、status 過濾
7. **時間軸**：拖曳時間滑桿，查看圖譜演變

## 參考

- [ideagraph 後端模組](../../../core/src/modules/ideagraph/README.md)
- [P7 藍圖](../../../docs/blueprint/p7-ideagraph.md)
