# Voices — 共用 reference audio 庫

> Schema v2（2026-05-20）：升級 meta.yaml 結構 + 新增 INDEX.yaml 全域索引。
> Voice ID 仍然扁平（CLI `--voice=master` 不變），物理路徑與邏輯名解耦。

---

## 檔案結構

```
voices/
├── INDEX.yaml                   # 全域索引（tag-based query 入口）
├── README.md                    # 本檔
├── .gitignore                   # *.wav / *.m4a / *.mp3 / *.flac 排除
│
├── master.wav                   # voice_id=master 的預設 reference audio
├── master_16k_8s.wav            # variant（IndexTTS-2 / VibeVoice 偏好 8s 版）
├── master.transcript            # 對應逐字稿
├── master.meta.yaml             # Schema v2 metadata
│
├── xinran.wav
├── xinran.transcript
└── xinran.meta.yaml
```

---

## 命名規約

| 物件 | 規約 | 例 |
|---|---|---|
| voice_id | 全小寫 + 連字號 | `master`, `xinran`, `narrator-deep` |
| 預設 audio | `{voice_id}.wav` | `master.wav` |
| variant audio | `{voice_id}_{sr}_{dur}.wav` | `master_16k_8s.wav` |
| transcript | `{voice_id}.transcript` | `master.transcript` |
| meta | `{voice_id}.meta.yaml` | `master.meta.yaml` |

---

## meta.yaml Schema v2

每個 voice 都應有完整 meta.yaml，含：

```yaml
voice_id: master
display_name: 少爺
author: <name>
recorded_at: <date>

language: zh-TW                  # IETF tag: zh-TW / zh-CN / en / ja / ko
gender: male                     # male / female / neutral
style: [conversational, technical]
age_range: 30-40

source:
  raw: <原始錄音檔>
  intermediate_refs: [...]

processed:                       # audio-ops 處理紀錄
  - { op: ffmpeg_resample, applied: true }
  - { op: denoise,         applied: false }
  - { op: vad_trim,        applied: false }
  - { op: normalize,       applied: false }

variants:                        # 多個 sample-rate / 時長版本
  - file: master.wav
    sample_rate: 16000
    duration_s: 5.0
    preferred_engines: [indextts2_base, indextts2_jmica, index_tts]
  - file: master_16k_8s.wav
    sample_rate: 16000
    duration_s: 8.0
    preferred_engines: [indextts2_base, indextts2_jmica, vibevoice]

transcript_file: master.transcript

notes: |
  ...
```

---

## 現有 voice 一覽

請參考 [`INDEX.yaml`](./INDEX.yaml) 的 `voices:` 與 `tag_index:` 區塊。

當前 2 個 voice：
- **master**（少爺主音色，zh-TW，male，conversational+technical，2 variants）
- **xinran**（心然，zh-CN，female，literary+calm，1 variant）

---

## 新增 voice 流程

### 標準流程（每個新 voice 都跑一次）

```bash
# Step 1 — 放原始錄音
cp <your-recording>.wav ~/workshop/stations/tts/voices/<voice_id>.wav

# Step 2 — 若是 48kHz stereo 等高品質原檔，先 downsample 給 IndexTTS-2 用
cd ~/workshop/stations/tts/voices
ffmpeg -i <voice_id>.wav -ar 16000 -ac 1 <voice_id>_16k.wav

# Step 3 — 跑 ASR 產 transcript 初稿（用 STT station port 10200）
curl -s -X POST "http://127.0.0.1:10200/transcribe?path=$(pwd)/<voice_id>_16k.wav&language=zh-TW&engine=apple&format=text" \
  > <voice_id>.transcript

# Step 4 — 寫 meta.yaml（複製 master.meta.yaml 改欄位）
$EDITOR <voice_id>.meta.yaml

# Step 5 — 跑 audio-ops 強化（降噪 + VAD 裁剪 + 響度標準化）⭐
~/.local/bin/python3 ~/workshop/stations/tts/scripts/voice_enhance.py <voice_id>
# 或一次跑所有 voice：
~/.local/bin/python3 ~/workshop/stations/tts/scripts/voice_enhance.py --all

# Step 6 — 把 <voice_id>.wav 換成 enhanced 版本（讓 station 自動用乾淨版）
cp <voice_id>.wav <voice_id>_original.wav    # 備份
cp <voice_id>_enhanced.wav <voice_id>.wav

# Step 7 — 登錄到 INDEX.yaml（手動 Edit 加 voices[] 與 tag_index[] 條目）
$EDITOR INDEX.yaml

# Step 8 — 同步到 win-gpu（rsync 不可用，用 tar pipe）
cd ~/workshop/stations/tts/voices
tar -czf - --exclude='*_original*' . \
  | ssh win-gpu 'tar -xzf - -C /mnt/c/Users/User/workshop-station/stations/tts/voices'
# 也同步到 WSL2 path（給 worker_trio_daemon 用）：
tar -czf - --exclude='*_original*' . \
  | ssh win-gpu 'tar -xzf - -C workshop/stations/tts/voices'
```

### voice_enhance.py 自動化

`~/workshop/stations/tts/scripts/voice_enhance.py` 是核心強化腳本：

| 用法 | 說明 |
|---|---|
| `voice_enhance.py <voice_id>` | 處理單個 voice |
| `voice_enhance.py --all` | 處理所有 `*.meta.yaml` 對應的 voice |
| `voice_enhance.py --all --dry-run` | 列出會處理哪些，不實際跑 |
| `voice_enhance.py master --json` | JSON manifest 輸出（給其他工具消費） |

**內部 filter chain（純 ffmpeg，零外部依賴）**：

```
highpass=80           砍 80Hz 以下風雜音
afftdn=nr=12:nf=-25   FFT 降噪 12dB
silenceremove         VAD-like 頭尾靜音裁剪 (-40dB threshold)
loudnorm=I=-16        EBU R128 響度標準化
aformat → 16k mono    TTS engine 偏好規格
```

腳本自動：
- 找每個 voice 的「主 variant」（優先 16kHz mono，fallback `<voice_id>.wav`）
- 跑 chain 產 `<voice_id>_enhanced.wav`
- sed-like 更新 `meta.yaml` 的 `processed[]` 標 `applied: true`（denoise/vad_trim/normalize 三項）
- 印 markdown manifest，提示 variants[] 該補的條目

> **為何用 ffmpeg 不用 audio-ops**：本機 `sherpa_onnx` wheel 缺 `libonnxruntime.1.24.4.dylib`，重灌會影響 STT station。ffmpeg 三 filter 對應效果近似且零依賴，跨平台一致（Mac / WSL2 / Linux）。

---

## 規模擴展

預期 voice 庫從 2 → 30+，分類維度：

| 維度 | 值 |
|---|---|
| language | zh-TW / zh-CN / en / ja / ko / ... |
| gender | male / female / neutral |
| style | conversational / formal / literary / technical / casual / dramatic / calm |
| author | 自錄 / 公開資料集 / 授權內容 |
| sample_rate | 16k (IndexTTS-2 / VibeVoice) / 22k (cosyvoice) / 44k (高品質) |

**voice_id 永遠扁平不分資料夾**（保 CLI 介面穩定），station / SDK 透過 `INDEX.yaml` 的 `tag_index` 做篩選。

---

## Roadmap

| Phase | 範圍 | 狀態 |
|---|---|---|
| 1 | meta.yaml schema v2 + INDEX.yaml + README v2 | ✅ 2026-05-20 |
| 1+ | 4 個新 voice (DIDI/GY/JADE/Sean) downsample + ASR transcript + meta | ✅ 2026-05-20 |
| 3 | voice_enhance.py 自動化（ffmpeg-based denoise + vad_trim + normalize） | ✅ 2026-05-20 |
| 2 | voices/ 子資料夾結構（變體集中）+ 頂層 symlink backward compat | TBD |
| 4 | Station v3 API：voice variant 路由（根據 lang + sr 自動選 variant） | TBD |
