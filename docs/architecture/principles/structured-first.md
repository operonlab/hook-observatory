# 結構化優先，AI 猜測最後 (Structured First, AI Guess Last)

> 永遠優先使用結構化資料來源，AI 推論僅作為最後手段。

## 原則摘要

讀取結構化資料（API 回應、DOM 元素、Correlation ID、資料庫欄位）遠優於讓 AI 從非結構化內容中猜測。結構化存取更快、更可靠、更便宜、且可重現。AI 推論應僅在結構化管道不可用時才啟用。

靈感來源：ghost-os 的核心洞見 —— macOS AX Tree 直接讀取的成功率與效率遠超 screenshot + VLM 像素猜測。

## 五層 Fallback 階梯

```
Layer 1: Direct API / Structured Data    ← 最快、最可靠
Layer 2: DOM / AX Tree traversal         ← 結構化，平台相關
Layer 3: Semantic search / Embedding      ← AI 輔助但有錨定
Layer 4: LLM inference from context       ← AI 詮釋
Layer 5: Vision / Screenshot analysis     ← 最後手段，最昂貴
```

每一層只在上一層不可用時才降級。設計時應盡量讓系統停留在 Layer 1-2。

## Workshop 應用場景

| 場景 | 結構化做法 (優先) | AI 猜測做法 (避免) |
|------|-------------------|-------------------|
| 瀏覽器自動化 | DOM selector / AX Tree 定位元素 | Screenshot + VLM 辨識像素位置 |
| 事件追蹤 | Explicit Correlation ID (`ContextVar`) | AI 從 log 推斷事件關聯 |
| 資料擷取 | API 結構化欄位、JSON schema | LLM 解析非結構化文字 |
| 健康監測 | AX element 驗證、HTTP status code | 像素比對截圖差異 |
| 工作流重播 | Deterministic recipe (nodeflow DAG) | AI 重新詮釋歷史操作 |
| Capture 分類 | Adapter 規則匹配 + 欄位對應 | 純 LLM 猜測目標模組 |

## 反模式

1. **Screenshot-First 測試**：用截圖比對驗證 UI 狀態，而非檢查 DOM 屬性或 API 回應
2. **LLM 萬能解析**：所有資料都丟給 LLM 解讀，即使來源有結構化 API
3. **省略 Correlation ID**：不埋追蹤 ID，事後靠 AI 從 timestamp 猜因果關係
4. **Pixel Assertion**：用視覺相似度判斷功能是否正常，忽略可直接查詢的狀態欄位

## 與既有原則的關聯

- **KISS**：結構化讀取比 AI 推論更簡單、更直接
- **Fail Fast**：結構化管道的錯誤立即可見；AI 猜測的錯誤可能靜默通過
- **SSOT**：結構化資料本身就是 single source of truth；AI 推論是衍生猜測
- **可觀察性**：結構化 trace > AI 回溯分析

## 設計檢查清單

新功能設計時自問：

- [ ] 這個資訊是否有結構化來源（API、DB 欄位、DOM 屬性）？
- [ ] 如果有，是否直接使用了結構化來源？
- [ ] AI 推論是否僅用在「無結構化替代方案」的場景？
- [ ] 是否為未來的結構化升級預留了介面（即使當前用 AI fallback）？
