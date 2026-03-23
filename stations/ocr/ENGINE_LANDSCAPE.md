# OCR Engine Landscape 2025-2026

> Last updated: 2026-03-22

## 範式轉移

傳統 OCR pipeline（偵測→辨識→後處理）已被**端到端 Vision-Language Model (VLM)** 取代。
Qwen-VL 家族成為事實標準基底模型。

## Benchmark 排名

### OmniDocBench（CVPR 2025，文件解析綜合分）

| 排名 | 模型 | 分數 |
|------|------|------|
| 1 | **PaddleOCR-VL 1.5** | **94.5** (SOTA) |
| 2 | PaddleOCR-VL 7B | 92.86 |
| 3 | PaddleOCR-VL 0.9B | 92.56 |
| 4 | MinerU 2.5 | 90.67 |
| 5 | MonkeyOCR-pro-3B | 88.85 |
| 6 | dots.ocr 3B | 88.41 |
| 7 | Gemini 2.5 Pro | 88.03 |
| — | GPT-4o | 85.80 |
| — | Mistral OCR 3 | 79.75 |

### olmOCR-Bench（1,403 PDF / 7,010 測試案例）

| 排名 | 模型 | 分數 | 參數 | 速度 | 成本/百萬頁 |
|------|------|------|------|------|------------|
| 1 | **Chandra 2** | **85.9** | 9B+ | ~1.3 p/s | — |
| 2 | LightOnOCR-2-1B | 83.2 | 1B | — | — |
| 3 | Chandra v0.1 | 83.1 | 9B | 1.29 p/s | $605 |
| 4 | olmOCR 2 | 82.4 | 7.7B | 1.78 p/s | $439 |
| 5 | PaddleOCR-VL | 80.0 | 0.9B | 2.20 p/s | $355 |
| 6 | dots.ocr 3B | 79.1 | 3B | 1.94 p/s | $402 |
| 7 | Marker | 76.1 | — | 25 p/s (batch) | — |
| 8 | DeepSeek-OCR | 75.7 | 3B | 4.65 p/s | $168 |
| 9 | LightOnOCR 1B | 76.1 | 1B | 5.55 p/s | **$141** |

### Datalab ELO（5,005 份真實文件盲測）

| 排名 | 模型 | ELO |
|------|------|-----|
| 1 | Chandra Accurate | 1798 |
| 2 | Chandra Balanced | 1638 |
| 3 | Chandra Fast | 1528 |
| 4 | dots.ocr | 1489 |
| 5 | olmOCR 2 | 1387 |
| 6 | DeepSeek OCR | 1336 |
| 7 | RolmOCR | 1324 |

## 模型速查

| 模型 | 參數 | 授權 | GPU 需求 | 適用場景 |
|------|------|------|---------|---------|
| **PaddleOCR PP-OCRv5** | 傳統 | Apache-2.0 | CPU OK | 中文印刷+手寫，無 GPU 環境 |
| **PaddleOCR-VL 1.5** | 0.9B~7B | Apache-2.0 | 需 GPU | OmniDocBench SOTA，生產首選 |
| **Chandra 2** | 9B | — | 需 GPU | olmOCR-Bench + ELO 雙冠王 |
| **MonkeyOCR-pro 3B** | 3B | — | 需 GPU | 超越 GPT-4o 和 Gemini 2.0 Flash |
| **Marker** | — | GPL-3.0 | 需 GPU | 大批量 PDF→Markdown，25 p/s |
| **LightOnOCR 1B** | 1B | — | 需 GPU | 最便宜 $141/百萬頁 |
| **olmOCR 2** | 7.7B | 全開源 | 需 GPU | 資料+模型+程式碼全開 |
| **DeepSeek-OCR** | 3B (570M active) | — | 需 GPU | 20x 視覺壓縮，token 敏感 |
| **RolmOCR** | 7B | Apache-2.0 | 需 GPU | Qwen2.5-VL fine-tune，速度優先 |
| **GOT-OCR 2.0** | — | MIT | 需高階 GPU | 研究用，生產已不建議 |
| **Surya** | — | GPL-3.0 | 需 GPU | 版面分析+閱讀順序 |
| **Tesseract** | 傳統 | Apache-2.0 | CPU only | 大量印刷文字批次，手寫 <50% |
| **Mistral OCR 3** | 閉源 | 閉源 | API | 手寫+掃描，$1/千頁 |

## 我們的 Station 引擎定位（v0.2.0）

```
apple      — 快速免費，一般圖片首選（macOS 限定）
paddle     — 中文主力，手寫+印刷最佳開源（CPU friendly）
tesseract  — 暗色背景截圖 fallback
claude     — 複雜圖表、極端手寫（但 Haiku 會幻覺）
gemini     — 雲端備援，本地引擎都失敗時
```

## 升級路線圖

### Phase 1（已完成）
- [x] PaddleOCR PP-OCRv5 引擎
- [x] 前處理 pipeline（CLAHE + denoise + deskew）
- [x] 智慧前處理開關（auto/on/off）

### Phase 2（潛在）
- [ ] PaddleOCR-VL 0.9B — 最小升級路徑，從傳統 OCR 到 VLM
- [ ] Marker 整合 — 大批量 PDF→Markdown

### Phase 3（未來）
- [ ] Chandra 2 — 需 GPU，精度王
- [ ] 智慧引擎路由 — 根據圖片特徵自動選引擎

## 實測對比：手寫發票（2026-03-22）

| 指標 | Apple Vision | PaddleOCR PP-OCRv5 |
|------|-------------|-------------------|
| 高信心區塊 | 8 | **44** (+450%) |
| 買方統編 | ❌ | ✅ 93529359 [0.99] |
| 銷售額 | ⚠️ ~$231,255 | ✅ $237,255 [0.90] |
| 稅額 | ❌ | ✅ $11,863 [0.95] |
| 總計 | ❌ | ✅ $249,118 [0.98] |
| 數學驗證 | ❌ | ✅ 三重通過 |

## 五大趨勢

1. **參數效率革命** — 0.9B 打贏 GPT-4o
2. **成本暴跌** — 自託管比 API 便宜 167 倍
3. **Benchmark 趨近飽和** — olmOCR-Bench 76→85.9
4. **小模型稱王** — LightOnOCR 1B、PaddleOCR-VL 0.9B
5. **Qwen-VL 成為基底標準** — RolmOCR、Chandra、MonkeyOCR 全基於此

## Sources

- [CodeSOTA OCR Benchmarks](https://www.codesota.com/ocr)
- [Datalab Overall OCR Benchmark (ELO)](https://www.datalab.to/benchmark/overall)
- [Modal: 8 Top Open-Source OCR Models](https://modal.com/blog/8-top-open-source-ocr-models-compared)
- [PaddleOCR-VL 1.5 Announcement](https://howaiworks.ai/blog/paddleocr-vl-1-5-announcement)
- [Chandra 2: Saturating the olmOCR Benchmark](https://www.datalab.to/blog/saturating-the-olmocr-benchmark)
- [Reducto: Introducing RolmOCR](https://reducto.ai/blog/introducing-rolmocr-open-source-ocr-model)
- [DeepSeek-OCR Paper](https://arxiv.org/html/2510.18234v1)
