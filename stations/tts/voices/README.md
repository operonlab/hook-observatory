# Voices — 共用 reference audio 庫

Voice ID 規約：`{speaker}` 全小寫，每個 voice 一組三件套：

```
{voice_id}.wav          # reference audio (5-15s)
{voice_id}.transcript   # 對應文字（給 cosyvoice / qwen3tts zero_shot 用）
{voice_id}.meta.yaml    # 語言 / 取樣率 / 時長 / 來源
```

## master

少爺主音色。Reference 來源：`outputs/tts-finetune-test/v3/ref/master_ref_*.wav`。

| 檔案 | 取樣率 | 時長 | 用途 |
|---|---|---|---|
| `master.wav` | 22050 Hz | ~5s | 預設（cosyvoice 系列偏好 22050）|
| `master_16k_8s.wav` | 16000 Hz | ~8s | IndexTTS-2 / VibeVoice 偏好 |
| `master_22k_5s.wav` | 22050 Hz | ~5s | cosyvoice v3 native |

在 win-gpu 部署時：

```bash
# Mac → win-gpu 同步 voices/
rsync -av stations/tts/voices/ win-gpu:~/workshop/stations/tts/voices/
```

實際 wav 檔不入 git（透過 `voices.gitignore` 排除），由部署腳本同步。
