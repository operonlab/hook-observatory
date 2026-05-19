# Deploy Guide — TTS Station v0.3 (v2 multi-engine integration)

對應 INTEGRATION-PLAN.md。Mac 端寫 code，win-gpu 端跑模型。

## 架構

```
Mac (開發) ──[Fleet dispatch / SSH / HTTP]──► win-gpu (Windows + WSL2)
                                                  │
                                                  ├─ stations/tts/main.py (port 10201)
                                                  │   ├─ /v2/synthesize (auto routing)
                                                  │   └─ /v2/engines + /v2/healthz
                                                  │
                                                  ├─ runners/run_cosyvoice_v3.py  ── conda env "cosyvoice"
                                                  ├─ runners/run_cosyvoice_v3.py  ── WSL2 .venvs/cosyvoice_vllm
                                                  ├─ runners/run_indextts2.py     ── Win lab/indextts/.venv
                                                  ├─ runners/run_vibevoice.py     ── WSL2 ~/VibeVoice
                                                  └─ runners/run_qwen3tts.py      ── WSL2 ~/qwen3tts_models
```

## win-gpu 部署 SOP

### 0. 前置（一次性）

| Engine | Venv 已存在於 win-gpu？ | 備註 |
|---|---|---|
| cosyvoice_v3_native | `anaconda3/envs/cosyvoice` | 少爺已建（2026-05-18 deploy 紀錄）|
| cosyvoice_v3_vllm | `~/.venvs/cosyvoice_vllm` (WSL) | 少爺已建（2026-05-18 wedge 修復）|
| indextts2_* | `lab/indextts/.venv` (Windows uv) | 少爺已建 |
| vibevoice | 共用 `~/.venvs/cosyvoice_vllm` (WSL) | 確認 vibevoice 套件已安裝在這個 venv |
| qwen3tts_gpu | 共用 `~/.venvs/cosyvoice_vllm` (WSL) | transformers + torch 已有 |

每個 venv 各自 `pip install opencc-python pykakasi soundfile numpy`（runner 預處理用）。

### 1. 拉 code

```bash
ssh win-gpu
cd ~/workshop
git fetch
git checkout feature/tts-station-integration
git pull
```

### 2. 安裝 station 主 venv

```bash
cd ~/workshop/stations/tts
uv sync   # 安裝 fastapi+uvicorn+httpx+pyyaml+pydantic
```

無需在主 venv 裝 cosyvoice/torch — runner 走自己的 venv。

### 3. 同步 voices/

Mac 端：

```bash
rsync -av outputs/tts-finetune-test/v3/ref/ win-gpu:~/workshop/stations/tts/voices/
```

或在 win-gpu 端：

```bash
cp ~/workshop/lab/cosyvoice/master_ref_*.wav ~/workshop/stations/tts/voices/
mv ~/workshop/stations/tts/voices/master_ref_5s_22k.wav ~/workshop/stations/tts/voices/master.wav
```

### 4. 起 service

```bash
cd ~/workshop/stations/tts
.venv/Scripts/python.exe main.py    # Windows
# 或 nohup .venv/bin/python3 main.py > tts.log 2>&1 &   # WSL
```

驗證：

```bash
curl http://127.0.0.1:10201/health
curl http://127.0.0.1:10201/v2/healthz   # 6 engine 健康狀態
curl http://127.0.0.1:10201/v2/engines    # capability 表
```

### 5. Smoke test

```bash
cd ~/workshop/stations/tts
TTS_LIVE=1 .venv/Scripts/python.exe -m pytest tests/smoke_test_v2.py -v
```

預期：4 個 engine 各跑一句 + base64/numpy/lifecycle test 通過。

### 6. 註冊到 service registry（Mac 端）

`scripts/workshop_services.py` 中 tts station 已存在，不必改。

**sentinel binary rebuild**（本 PR 加了 `"tts"` 進 `WORKSHOP_SERVICES`）：

```bash
cd ~/workshop/stations/sentinel && cargo build --release
launchctl kickstart -k gui/$UID/workshop.sentinel
```

驗證：`curl http://127.0.0.1:4101/checks | jq '.[] | select(.name=="tts")'` 應該見到 tts 在 sentinel 視野內，且 remediation 在 service-down 時會 auto-restart。

### 7. ~/.local/bin/workshop-tts symlink

```bash
ln -sf ~/workshop/stations/tts/bin/workshop-tts ~/.local/bin/workshop-tts
which workshop-tts
workshop-tts --help
```

### 8. MCP 註冊

```bash
# Edit ~/.mcpproxy/mcp_config.json，加 "tts" entry
{
  "tts": {
    "command": "/Users/joneshong/.local/bin/python3",
    "args": ["/Users/joneshong/workshop/mcp/tts/server.py"]
  }
}
```

mcpproxy 自動 reload。Claude Code 開新 session 後 tools 即可見。

### 9. Skill 部署

```bash
mkdir -p ~/.claude/skills/tts
cp -r ~/workshop/stations/tts/skill/* ~/.claude/skills/tts/
```

## Mac → win-gpu 跨機器呼叫

### 選項 A：HTTP 直連（有 Tailscale）

```python
from sdk_client.tts import TTSClient

client = TTSClient(base_url="http://win-gpu.tail-scale.ts.net:10201")
res = client.synthesize_v2("Hello", lang="en", out_path="/tmp/o.wav")
# audio_path 在 win-gpu 端，要 scp 回 Mac
```

更實用：用 `output="base64"`，直接拿到音檔 bytes：

```python
res = client.synthesize_v2("Hello", lang="en", output="base64")
import base64
Path("/tmp/o.wav").write_bytes(base64.b64decode(res["audio_base64"]))
```

### 選項 B：Fleet dispatch

```python
from sdk_client.fleet import dispatch

result = dispatch(
    target="win-gpu", mode="gpu",
    cmd=["workshop-tts", "--text", "你好", "--lang", "zh", "--out", "/tmp/o.wav"],
)
# Fleet 自動 scp /tmp/o.wav 回 Mac
```

## 排錯 SOP

| 症狀 | 可能原因 | 處理 |
|---|---|---|
| `/v2/healthz` engine.ok=false | python/runner 路徑不存在 | 檢查 manifest.yaml 上 venv 路徑 |
| runner timeout 300s | model 首次 load 慢 / GPU wedge | `nvidia-smi` 看 GPU；boot Windows 重 load nvlddmkm |
| RuntimeError "no output" | ref.wav 找不到 | 看 voices/master.wav 是否存在 |
| Japanese 發音崩 | pykakasi 沒裝在對應 venv | `pip install pykakasi` 進 cosyvoice venv |
| 繁體中文音字錯亂 | OpenCC 沒裝 | `pip install opencc-python` 進對應 venv |
| VRAM OOM | 2 engine 同時 keep alive | `POST /v2/lifecycle/sweep` 主動 unload |
| WSL2 GPU wedge | 已知問題 | 參考 memory `wsl2-rtx3090-vllm-gpu-wedge-2026-05-18.md`，cold boot Windows |

## launchd / Cronicle 自動拉起（後續）

Phase 5：寫 plist + Cronicle job 把 service 設為 boot-start，目前手動。

## 驗收 checklist

- [ ] `curl /v2/healthz` 6 engine 都 ok=true
- [ ] `workshop-tts list-engines` 顯示 6 engine + healthy
- [ ] `workshop-tts --text "你好" --lang zh` 產 wav
- [ ] `workshop-tts --text "Hello" --lang en` 產 wav (RTF ~0.43)
- [ ] `workshop-tts --text "おはよう" --lang ja` 產 wav
- [ ] Mac Claude Code session 內 MCP tool `tts_synthesize` 可呼叫
- [ ] Skill `/tts` 觸發詞「合成語音」可激活
