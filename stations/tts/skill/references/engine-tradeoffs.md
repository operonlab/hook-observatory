# Engine Trade-offs — v3 系列 6 個引擎特性對照

對應 manifest.yaml capability 欄位。少爺實際測試結果見 `outputs/tts-finetune-test/v3/COMPARE.md`。

## 詳細特性表

| 引擎 | 環境 | VRAM | RTF | 中 | 英 | 日 | 韓 | 多 speaker | streaming | 備註 |
|---|---|---|---|---|---|---|---|---|---|---|
| cosyvoice_v3_native | Win native | 5GB | 1.76 | ✓ | ✓ | ✓ | ✗ | ✗ | chunk-fake | baseline，最穩定 |
| cosyvoice_v3_vllm | WSL2 | 7.5GB | **0.43** | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ true | **en 預設**，最快 |
| indextts2_base | Win native | 7GB | 0.7 | **✓** | **✓** | ✗ | ✗ | ✗ | chunk-fake | **zh/en 少爺偏好** |
| indextts2_jmica | Win native | 7GB | 0.7 | ✗* | ✗* | **✓** | ✗ | ✗ | chunk-fake | **ja 少爺偏好**，中英 catastrophic forgetting |
| vibevoice | WSL2 | 8GB | 1.2 | ✓ | ✓ | ✗ | ✗ | **✓** | ✓ true | podcast / dialogue 唯一選項 |
| qwen3tts_gpu | WSL2 | 3GB | 1.19 | ✓ | ✓ | ✓ | **✓** | ✗ | ✗ | 唯一支援 ko，zero-shot 必填 ref_text |

*indextts2_jmica routing 已強制只接 ja，傳其他語言會 ValueError

## 選擇決策樹

```
任務需要多 speaker？ ────────── yes ─→ vibevoice
                                no
                                 ↓
任務是日語？ ──────────────────── yes ─→ indextts2_jmica
                                no
                                 ↓
任務是韓語？ ──────────────────── yes ─→ qwen3tts_gpu
                                no
                                 ↓
追求最快（批次 / podcast 預錄）？ yes ─→ cosyvoice_v3_vllm (RTF 0.43)
                                no
                                 ↓
中文音色品質優先？ ──────────── yes ─→ indextts2_base
                                no
                                 ↓
英語音色品質優先？ ──────────── yes ─→ cosyvoice_v3_vllm
                                no
                                 ↓
WSL2 不可用（GPU wedge 復發）？  yes ─→ cosyvoice_v3_native (baseline，慢但穩)
```

## VRAM 預算

24GB 卡同時容納：
- 1 個 indextts2 (7GB) + 1 個 cosyvoice_v3 (5-7GB) + 1 個 qwen3tts (3GB) = ~17GB ✓
- **不可**同時 indextts2_base + indextts2_jmica（14GB）+ cosyvoice (5-7GB) + vibevoice (8GB) = 27-29GB ✗

lifecycle.py 預設 idle 60s 自動 unload，跨語言切換時自動釋 VRAM 給新引擎。

## RTF 對比實測

少爺 2026-05-18 在 win-gpu 實測（master_ref_8s_16k.wav，wsl2-rtx3090-vllm-gpu-wedge 修復後）：
- cosyvoice_v3_native: RTF **1.76**
- cosyvoice_v3_vllm:   RTF **0.43**（加速 4.1×）

## Ref audio 規格需求

| 引擎 | 偏好 sr | 偏好時長 | ref_text 必填？ |
|---|---|---|---|
| cosyvoice_v3_* | 16000 Hz | 5-10s | 同語 zero_shot 建議；cross-lingual 不需要 |
| indextts2_* | 16000 Hz | 5-8s | 不需要 |
| vibevoice | 24000 Hz | 3-30s | **是**（多 speaker 場景每位 speaker 各一份） |
| qwen3tts_gpu | 16000-24000 | 3-15s | **是** |

stations/tts/voices/ 提供 master 三規格：
- master.wav (22050 Hz, 5s) — 預設
- master_16k_8s.wav (16000 Hz, 8s) — IndexTTS/VibeVoice 偏好
- master_22k_5s.wav (22050 Hz, 5s) — cosyvoice 偏好

引擎 runner 自動挑選最匹配的 ref，少爺不需指定。

## 已知 caveat（manifest.yaml 之外）

- **CosyVoice 第一次 inference 雜音** — runner 啟動時 dummy warmup 解
- **CosyVoice 日文** — 必經 pykakasi 轉片假名 + 空格切詞，否則發音崩
- **IndexTTS 繁體** — BPE 不認，必經 OpenCC t2s
- **VibeVoice 不支援 ja** — 收到 lang=ja 會 ValueError，路由已排除
- **qwen3tts 0.6B-Base 是 zero-shot** — 不要拿 0.6B-CustomVoice（不能 zero-shot，少爺記憶踩過）
- **WSL2 vllm 第一次 cold-start** — 1-2 分鐘載入 vllm engine，後續 keep alive 期間每次 < 1s
- **VLLM GPU wedge** — TDR Registry 已設防（TdrLevel=3, HAGS off）；若復發 boot Windows + reload nvlddmkm

## 後續擴充（不在 Phase 1-4）

- emotion control（cosyvoice instruct + qwen3tts emotion vector）
- 真 streaming endpoint（SSE/WebSocket）
- voice market（多 speaker 共享庫）
- 觀測 metrics（per-synth RTF 入 logger）
