"""structured_run.py — 統一的 subprocess 執行包裝器。

提供結構化的執行報告，可選擇性地呼叫 LiteLLM 產生摘要。
設計原則：
  - LiteLLM 連不上時不 crash，gracefully skip summary
  - 不依賴 requests library，純 stdlib (urllib.request)
  - 不干涉 grc_runner.py 的流程

使用範例::

    from schedules.lib.structured_run import structured_run

    result = structured_run(
        [str(PYTHON), str(SCRIPT)],
        label="memvault-extract-step1",
        timeout=3600,
        summarize=True,
    )
    if not result.success:
        log(f"Step failed (exit {result.returncode})")
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

# ── LiteLLM 本地端點設定 ──────────────────────────────────────────────────────

_LITELLM_URL = "http://127.0.0.1:4000/v1/chat/completions"
_LITELLM_API_KEY = "sk-litellm-local-dev"

# 摘要 prompt：精簡指令，只看 stdout 前段
_SUMMARIZE_SYSTEM = (
    "你是一個排程日誌分析器。"
    "用 1-2 句繁體中文摘要以下程式輸出的執行結果，"
    "重點是：成功/失敗、處理了多少項目、有無異常。"
    "不要重複貼出原始日誌內容。"
)


# ── 資料結構 ──────────────────────────────────────────────────────────────────


@dataclass
class RunResult:
    """subprocess 執行結果，附帶計時與可選摘要。"""

    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    summary: str | None = None
    # success 由呼叫端或預設邏輯決定（returncode == 0）
    success: bool = field(init=False)

    def __post_init__(self) -> None:
        # 以 returncode 決定 success，呼叫端不需手動設定
        self.success = self.returncode == 0


# ── LiteLLM 摘要（best-effort）─────────────────────────────────────────────


def _try_summarize(text: str, model: str) -> str | None:
    """呼叫 LiteLLM 產生摘要。連不上時回傳 None，不拋例外。"""
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": _SUMMARIZE_SYSTEM},
                {"role": "user", "content": text[:3000]},
            ],
            "max_tokens": 120,
            "temperature": 0.2,
        }
    ).encode()

    req = urllib.request.Request(  # noqa: S310
        _LITELLM_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_LITELLM_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, TimeoutError, OSError):
        # LiteLLM 尚未啟動或網路不通 → 靜默略過
        return None
    except (KeyError, IndexError, json.JSONDecodeError):
        # 回應格式異常 → 靜默略過
        return None


# ── 核心函式 ──────────────────────────────────────────────────────────────────


def structured_run(
    cmd: list[str],
    *,
    timeout: int = 300,
    capture_stdout: bool = True,
    summarize: bool = False,
    summarize_model: str = "grok-4-fast",
    label: str = "",
) -> RunResult:
    """執行子程序並回傳結構化結果。

    Args:
        cmd: 要執行的命令及引數列表。
        timeout: 最長等待秒數（預設 300s）。
        capture_stdout: 是否捕捉 stdout/stderr（預設 True）。
            若為 False，輸出直接印到終端，RunResult.stdout/stderr 為空字串。
        summarize: 是否呼叫 LiteLLM 摘要 stdout（預設 False）。
        summarize_model: LiteLLM 使用的模型（預設 grok-4-fast）。
        label: 顯示在執行報告的標籤（預設空字串）。

    Returns:
        RunResult dataclass，包含 returncode、stdout、stderr、
        duration_seconds、summary、success。
    """
    # ── 執行 ─────────────────────────────────────────────────────────────────
    t0 = time.monotonic()

    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=capture_stdout,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        # 超時：視為失敗，傳回特殊 returncode
        duration = time.monotonic() - t0
        result = RunResult(
            returncode=124,  # 慣例：timeout exit code
            stdout="",
            stderr=f"[structured_run] Command timed out after {timeout}s",
            duration_seconds=round(duration, 3),
            summary=None,
        )
        _print_report(result, label)
        return result

    duration = time.monotonic() - t0

    # ── 可選摘要 ──────────────────────────────────────────────────────────────
    summary: str | None = None
    if summarize and stdout.strip():
        summary = _try_summarize(stdout, summarize_model)

    result = RunResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=round(duration, 3),
        summary=summary,
    )

    # ── 列印結構化報告 ────────────────────────────────────────────────────────
    _print_report(result, label)
    return result


# ── 執行報告印出 ──────────────────────────────────────────────────────────────


def _print_report(result: RunResult, label: str) -> None:
    """列印結構化執行報告到 stdout。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_str = "OK" if result.success else f"FAILED (exit {result.returncode})"
    tag = f"[{label}] " if label else ""

    print(
        f"{tag}structured_run {ts} "
        f"duration={result.duration_seconds:.1f}s "
        f"status={status_str}",
        flush=True,
    )

    # 若有摘要，額外印一行
    if result.summary:
        print(f"{tag}  summary: {result.summary}", flush=True)
    # 若失敗且有 stderr，印出前 200 字協助 debug
    elif not result.success and result.stderr.strip():
        preview = result.stderr.strip()[:200].replace("\n", " ")
        print(f"{tag}  stderr: {preview}", flush=True)
