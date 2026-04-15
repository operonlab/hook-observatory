---
name: temporal-parse-opensource-assessment
description: TemporalNormalizer 開源評估：學術支撐、市場定位、架構決策，備用於未來 subtree split
type: project
---

## 開源評估結論

**值得做，但不急。** 目前維持 workshop 內部 ops，未來穩定後可 subtree split 成 `temporal-parse` PyPI 套件。

**Why:** 學術界已證明 hybrid rule+LLM 是正確方向（3 篇 paper），社群 ad-hoc 在做但零 formalized library。gap 明確。

**How to apply:** 開源時需從 NormalizerOp 抽成純函數 `parse_temporal(text, ref) → list[TemporalMatch]`，workshop 內部用 thin wrapper 消費。

## 學術支撐（3 篇核心 paper）

1. **Su et al. (2025)** — SCATE framework, arXiv:2507.06450
   - 把時間正規化定義為 symbolic composition + code generation
   - 結果超越純 LLM，但尚未公開 library

2. **Marín (2025)** — arXiv:2511.10654
   - 8 個 LLM 測試：prompt 格式改變造成 30-60% accuracy 波動
   - 結論：temporal constraint satisfaction cannot be learned via next-token prediction
   - 明確推薦 hybrid symbolic+neural architecture

3. **Garikaparthi (2026)** — "Can LLMs Perceive Time?", arXiv:2604.00010
   - GPT-5 temporal pairs accuracy 僅 18%
   - LLM 有命題知識但缺乏計算能力
   - 推薦外部計算基礎設施

## 市場定位

**不是**「又一個 temporal parser」或「繁中時間解析器」。
**是** 學術界已驗證的 hybrid pattern 的開發者工具化。

核心賣點：
- **TemporalIntent contract** — rule↔LLM 的 handoff schema，目前零競品
- **零外部依賴** — dateparser 6 deps、MS Recognizers 5 deps + emoji 衝突、Duckling 要 Docker
- **~400 行、0.04s/61 tests** — 小到可以直接 audit

繁中優先不是護城河（OpenCC 一套任何工具都行）。

## 多語言策略

不加 20 語言 keyword mapping。理由：
- TemporalIntent via LLM 本身就是多語言方案
- 加語言 = dateparser 路線（量大質差）
- 社群 PR 比我們猜更可靠

策略：Built-in zh-TW + en，其他語言走 LLM handoff，社群貢獻 keyword map。

## 開源時架構（備用）

```
temporal-parse/              ← PyPI 套件
├── temporal_parse/
│   ├── __init__.py          ← parse_temporal(), TemporalIntent, resolve_temporal_intent
│   ├── rules.py             ← regex + lookup tables
│   └── calendar.py          ← weekday/month/quarter 計算
└── tests/

workshop/libs/text-ops/      ← 內部消費
└── text_ops/temporal.py     ← TemporalNormalizer wraps temporal_parse
```

## 蠶食來源 LICENSE 注意

- dateparser: BSD-3 ← regex pattern 結構可用
- MS Recognizers-Text: MIT ← weekday 算法 + lookup tables 可用
- 兩者都是 permissive license，蠶食無法律風險
