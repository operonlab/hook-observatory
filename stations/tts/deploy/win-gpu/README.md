# win-gpu Deploy Bundle

把 workshop TTS station 部署到 win-gpu (Windows + WSL2 RTX 3090) 所需的所有檔案。

## 部署順序

### 0. 一次性前置（少爺已做的部分跳過）

- Windows host：anaconda3 + lab/cosyvoice (CosyVoice repo + 模型) + lab/indextts (IndexTTS-2 + ckpts)
- WSL2 Ubuntu：`~/.venvs/cosyvoice_vllm` venv + ~/VibeVoice + ~/qwen3tts_models 模型
- TDR Registry 已設（vllm GPU wedge 防護，少爺 2026-05-18 已修）

### 1. 拉 workshop sparse-checkout（Windows 端，PowerShell）

```powershell
# 拷貝這份 deploy 資料夾上去（或先 git clone 整個 workshop 再 sparse）：
scp -r stations/tts/deploy/win-gpu/ win-gpu:C:/Users/User/workshop-deploy/
ssh win-gpu
powershell -ExecutionPolicy Bypass -File C:\Users\User\workshop-deploy\setup-sparse-checkout.ps1
```

完成後 `C:\Users\User\workshop` 只有 `stations/tts + libs/sdk-client + mcp/tts + scripts + .claude/rules`，~50MB。

### 2. 部署 CLAUDE.local.md

```powershell
cp C:\Users\User\workshop-deploy\CLAUDE.local.md.template C:\Users\User\workshop\CLAUDE.local.md
# 編輯 confirm path 都對
```

### 3. 安裝 station 主 venv

```powershell
cd C:\Users\User\workshop\stations\tts
uv sync
```

### 4. 同步 voices/

```bash
# Mac 端：
rsync -av outputs/tts-finetune-test/v3/ref/ win-gpu:C:/Users/User/workshop/stations/tts/voices/
```

或從 win-gpu 端的 `lab/cosyvoice/master_ref_*.wav` 拷過去。

### 5. 各 engine venv 補裝預處理 deps

對 4 個會被呼叫的 venv 各跑一次：

```powershell
# anaconda env=cosyvoice
& "C:\Users\User\anaconda3\envs\cosyvoice\python.exe" -m pip install opencc-python pykakasi soundfile numpy

# lab/indextts 自己的 .venv
& "C:\Users\User\workshop\lab\indextts\.venv\Scripts\python.exe" -m pip install opencc-python soundfile numpy
```

```bash
# WSL：cosyvoice_vllm 共用 venv（vibevoice / qwen3tts_gpu 都用這個）
wsl bash -lc '/home/joneshong/.venvs/cosyvoice_vllm/bin/pip install opencc-python pykakasi soundfile numpy'
```

### 6. 註冊開機自啟（Task Scheduler）

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\User\workshop\stations\tts\deploy\win-gpu\install-autostart.ps1
# 立即測試：
Start-ScheduledTask -TaskName "Workshop TTS Service"
Get-Content C:\Users\User\workshop\stations\tts\tts.autostart.log -Wait -Tail 10
```

### 7.（可選）WSL vllm warmup systemd-user unit

```bash
wsl bash -lc '
  mkdir -p ~/.config/systemd/user
  cp /mnt/c/Users/User/workshop/stations/tts/deploy/win-gpu/wsl-tts-warmup.service ~/.config/systemd/user/tts-warmup.service
  systemctl --user daemon-reload
  systemctl --user enable --now tts-warmup.service
  systemctl --user status tts-warmup.service
'
```

### 8. 驗收

```powershell
curl http://127.0.0.1:10201/health
curl http://127.0.0.1:10201/v2/healthz | python -m json.tool
curl http://127.0.0.1:10201/v2/route?lang=en
```

預期：6 engine 全 ok，en routing → indextts2_base（少爺 2026-05-19 新預設）。

## 故障排查

| 症狀 | 處理 |
|---|---|
| Task Scheduler 不啟 | `Get-ScheduledTaskInfo -TaskName "Workshop TTS Service"` 看 LastTaskResult |
| 開機後 port 10201 沒起 | 看 tts.autostart.log |
| WSL warmup 一直失敗 | `journalctl --user -u tts-warmup.service` 看 GPU wedge 訊息 |
| indextts checkpoint 找不到 | 對齊 CLAUDE.local.md 內路徑 vs 實際 ckpt 位置 |

## 解除安裝

```powershell
Unregister-ScheduledTask -TaskName "Workshop TTS Service" -Confirm:$false
wsl bash -lc 'systemctl --user disable --now tts-warmup.service'
```
