# Next: Persistent Worker Pool (少爺 2026-05-19 規格)

當前架構（subprocess-per-call）每句 cold-load 模型 ~40-100s。少爺確認下個 session 改為 **常駐 worker daemon** 解 cold-start。

## 少爺規格（不可違反）

1. **idle_timeout 機制** — 模型 keep alive N 秒後沒呼叫 → 自動 unload 釋 VRAM
2. **一次只載一個模型** — `MODEL_POOL_MAX = 1`，跨 worker process 也是 global lock
3. **batch 支援** — 一次 request 可傳多句（避免 per-call overhead）

## 架構

```
station main.py (port 10201, Python 3.12)
  │ ── global _active_engine: str | None
  │ ── global _last_used: float
  │ ── background idle_sweeper task (每 30s 檢查)
  │
  ├─ spawn → worker_trio_daemon (常駐 Python, tts-trio venv)
  │           ├─ stdin: JSONL commands ({op:"load"|"synth"|"unload"|"healthz", ...})
  │           ├─ stdout: JSONL responses ({ok, audio_b64, sample_rate, error?})
  │           └─ 內部最多 1 engine in GPU
  │
  └─ spawn → worker_qwen3_daemon (常駐 Python, tts-qwen3 venv)
              └─ 同上協議
```

## 切 engine 流程（model_pool max=1）

每次 /v2/synthesize 進來：
1. 解析 target_engine（lang routing or explicit）
2. 看 `_active_engine`：
   - 同一個 → 直接送 synth command 到對應 worker
   - 不同 → 先發 `{op:"unload", engine:_active_engine}` 到舊 worker，等 ack
3. 發 `{op:"synth", engine:target_engine, text, lang, voice_id, ...}` 到 target worker
4. worker 內部若 engine 還沒 load → lazy load（第一次 ~40-100s，之後 1-5s）
5. 更新 `_active_engine = target_engine` + `_last_used = now()`

## idle_timeout 觸發 unload

```python
async def idle_sweeper():
    while True:
        await asyncio.sleep(30)
        if _active_engine and (time.monotonic() - _last_used) > IDLE_TIMEOUT_SEC:
            send_to_worker(_active_engine, {"op": "unload"})
            _active_engine = None
```

預設 `IDLE_TIMEOUT_SEC = 120`（2 min）

## Batch 規格

```python
POST /v2/synthesize/batch
{
  "items": [
    {"text": "句1", "lang": "zh", "voice_id": "master"},
    {"text": "句2", "lang": "zh", "voice_id": "master"},
    ...
  ],
  "engine": "auto",  # 或具體名
  "output": "file" | "buffer" | "base64"
}
```

Engine 一致時（auto routing 後）→ 全部送進同個 worker 一次處理（worker 內可選擇 真正 batch 推理 or sequential keep-alive）。

跨 engine batch（少見）→ split 成多次 worker call，但仍然只**一次 unload+load swap**。

## Worker daemon 協議

`workers/worker_daemon.py`（tts-trio + tts-qwen3 共用 base class，差別在 engine import）

```python
# stdin line 1: {"op": "load", "engine": "cosyvoice_v3_vllm"}
# stdout line 1: {"ok": true}
#
# stdin line 2: {"op": "synth", "engine": "cosyvoice_v3_vllm", "text": "你好", "lang": "zh", ...}
# stdout line 2: {"ok": true, "audio_b64": "...", "sample_rate": 24000, "duration_s": 3.5}
#
# stdin line 3: {"op": "unload"}
# stdout line 3: {"ok": true}
#
# stdin line 4: {"op": "healthz"}
# stdout line 4: {"ok": true, "loaded": null}  # 或 "loaded": "cosyvoice_v3_vllm"
```

## 對既有 code 的影響

| 既有 | 改造 |
|---|---|
| `engines/subprocess_bridge.py` | 改成 `engines/worker_pool_bridge.py` — 不再 spawn-per-call，改 dispatch 到 worker pool |
| `engines/cosyvoice_v3.py` 等 4 engine | 保留 PYTHON / RUNNER / CWD 設定（給 worker daemon 啟動用），不再被當作 subprocess 入口 |
| `lifecycle.py` | 簡化：直接整合進 station main.py 的 idle_sweeper |
| `runners/run_*.py` | 改造成 worker daemon mode — `while True: cmd = read_jsonl(stdin); dispatch(cmd)` |
| `routes_v2.py` | `/v2/synthesize` 內部改用 `WorkerPool.dispatch(req)` |

## 工作量估計

200-300 行新 code + 改造 ~150 行既有。建議分 commit：

1. WorkerDaemonBase + worker_trio_daemon.py + worker_qwen3_daemon.py
2. WorkerPool class（station 端）+ lifespan startup/shutdown
3. 改造 routes_v2.py 接入 WorkerPool
4. Batch endpoint /v2/synthesize/batch
5. 重跑 round 6 driver verification

## 風險

- Worker daemon crash 處理（auto-respawn or fail-loud）
- stdin/stdout 半個 message 緩衝（用 `\n` line-delimited + flush）
- GPU OOM 防護（雖然 max=1 但模型 load 過程仍可能 OOM）

## 不在這個 next-session 範圍

- 真正 batched GPU inference（單 model 並行 N 句）— 各 engine API 不一致，留更後面
- worker pool 跨機器（Mac → win-gpu HTTP 仍能用，但 worker 在 win-gpu 才有 GPU）
