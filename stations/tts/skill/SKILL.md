---
name: tts
description: This skill should be used when the user asks to "synthesize speech", "voice clone", "TTS", "做語音", "合成語音", "克隆音色", "讀出來", "幫我念", "podcast 合成", "多 speaker 對話", or discusses text-to-speech with the master voice or multilingual zero-shot voice cloning. Routes 中文/英文/日文 to 6 v3-series engines on win-gpu (cosyvoice_v3_native/vllm, indextts2_base/jmica, vibevoice, qwen3tts_gpu) via workshop-tts CLI.
disable-model-invocation: false
io:
  input:
    - mime: "text/plain"
      description: "Text to synthesize"
  output:
    - mime: "audio/wav"
      description: "Synthesized speech wav file"
---

# tts — Workshop TTS Station 統一語音合成

整合 6 個 v3 系列 zero-shot voice clone 引擎，跑在 win-gpu RTX 3090。
透過 `workshop-tts` CLI 自動路由 lang → engine，預設用少爺主音色 `master`。

## 啟動先決條件

1. win-gpu 端 `stations/tts/` service 已起（`launchctl kickstart -k workshop.tts`，port 10201）
2. Mac 端透過 Fleet dispatch / SSH 隧道連到 service
3. `~/.local/bin/workshop-tts` symlink 存在（指向 stations/tts/bin/workshop-tts）

健檢：

```bash
workshop-tts healthcheck       # 全 engine 健康狀態
workshop-tts list-engines      # 列 capability + RTF + VRAM
```

## 語言 → engine 自動路由（預設）

少爺主路線：中英日全走 indextts-2 系列；CosyVoice / Qwen3TTS 是 fallback；多人對話走 VibeVoice。

| 語言 | 預設引擎 | RTF | Fallback chain | 備註 |
|---|---|---|---|---|
| zh 中文 | `indextts2_base` | 0.7 | cosyvoice_v3_vllm → cosyvoice_v3_native → qwen3tts_gpu | 少爺偏好；繁體自動 OpenCC t2s |
| en 英文 | `indextts2_base` | 0.7 | cosyvoice_v3_vllm → cosyvoice_v3_native → qwen3tts_gpu | 少爺偏好（同音色一致性勝 RTF）|
| ja 日文 | `indextts2_jmica` | 0.7 | cosyvoice_v3_vllm → cosyvoice_v3_native → qwen3tts_gpu | jmica fine-tune，中英 catastrophic forgetting |
| ko 韓文 | `qwen3tts_gpu` | 1.19 | （只有 Qwen3 支援）| 唯一選項 |
| 多 speaker | `vibevoice` | 1.2 | （唯一）| podcast / dialogue |
| `--prefer-fast` | `cosyvoice_v3_vllm` | 0.43 | — | 顯式要求極速批次時走 vllm |

## 主要用法（CLI-first）

```bash
# 最簡：lang routing 自動選引擎
workshop-tts --text "你好" --lang zh                          # → indextts2_base → /tmp/tts_xxx.wav
workshop-tts --text "Hello world" --lang en                    # → cosyvoice_v3_vllm
workshop-tts --text "おはようございます" --lang ja             # → indextts2_jmica

# 指定 output path
workshop-tts --text "..." --lang zh --out /tmp/o.wav

# 強制引擎
workshop-tts --text "..." --lang en --engine cosyvoice_v3_native

# base64 給 web / JSON
workshop-tts --text "..." --lang zh --output base64

# Buffer 直接到 stdout（管 ffplay）
workshop-tts --text "..." --lang zh --output buffer | ffplay -nodisp -autoexit -

# 多 speaker podcast（vibevoice）
workshop-tts --text "[Speaker A] Hi [Speaker B] Hello" --lang en --engine vibevoice
```

## Routing 解釋 + 健康狀態

```bash
workshop-tts route --lang en --prefer-fast       # 顯示 chain
workshop-tts list-voices                          # 看 voices/ 內容
workshop-tts lifecycle status                     # idle engine 狀態
workshop-tts lifecycle sweep                      # 主動 unload idle engine（釋 VRAM）
```

## 跨機器（Mac → win-gpu）

stations/tts/ service 跑在 win-gpu。Mac 端透過 SDK / CLI 走 HTTP（透過 Tailscale 或本地 nginx proxy）。
細節見 `stations/tts/DEPLOY.md`。

## 重要 caveat

- **繁體輸入** → runner 自動 OpenCC t2s（所有引擎都吃簡體訓練）
- **日文** → CosyVoice 必經 pykakasi 轉片假名 + 空格切詞（runner 內處理）
- **indextts2_jmica 只接 ja** → 中英請走 indextts2_base，路由已預設正確
- **VRAM 競爭** → 6 engine 不能同時 keep alive，lifecycle 自動 60s idle unload
- **WSL engine** （cosyvoice_v3_vllm / vibevoice / qwen3tts_gpu）首次冷啟動 ~5-10s
- **zero-shot ref_text** → qwen3tts_gpu / cosyvoice zero_shot 模式必填，其他引擎可空

## 詳細 capability / trade-off

見 `references/engine-tradeoffs.md`。

## 不在這個 skill 範圍

- TTS fine-tune / 訓練 → 走 `lab/cosyvoice/`、`lab/indextts/` 各自 repo
- 老 Mac engine（edge/apple/elevenlabs/kokoro/mlx-qwen3-tts/f5-tts）→ 透過 v1 API 走 `workshop-tts` 不支援；直接呼叫 `client.synthesize(..., engine="apple")`
- 真 streaming 即時合成 → 目前 station 暴露 v1 `/synthesize/stream`，v2 streaming 開發中
