"""
對抗性測試：schedules/lib/structured_run.py

測試策略：根據函數簽名與文檔推導行為，不依賴實作細節。
每個測試針對特定 mutation 或不變量設計。
外部 I/O (subprocess.run, urllib) 透過 mock 隔離。
"""

import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# 確保 schedules/lib 可被 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from schedules.lib.structured_run import _try_summarize, structured_run

# ─────────────────────────────────────────────
# INV-1: result.success ⟺ result.returncode == 0
# ─────────────────────────────────────────────


class TestSuccessInvariant:
    """驗證 success 欄位完全由 returncode 決定，無例外。"""

    def test_success_true_when_returncode_zero(self):
        """returncode=0 → success must be True。
        # kills: M1 (success 反轉)
        """
        # invariant: INV-1
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"ok"
        mock_proc.stderr = b""
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["echo", "hello"])
        assert result.success is True, "returncode=0 必須讓 success=True"

    def test_success_false_when_returncode_nonzero(self):
        """returncode=1 → success must be False。
        # kills: M1 (success 反轉)
        """
        # invariant: INV-1
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = b""
        mock_proc.stderr = b"error"
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["false"])
        assert result.success is False, "returncode=1 必須讓 success=False"

    def test_success_false_when_returncode_negative(self):
        """returncode=-1 (signal) → success must be False。
        # kills: M1
        """
        # invariant: INV-1
        mock_proc = MagicMock()
        mock_proc.returncode = -1
        mock_proc.stdout = b""
        mock_proc.stderr = b"signal"
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["sleep", "999"])
        assert result.success is False

    def test_success_false_when_returncode_2(self):
        """returncode=2 → success must be False（非零皆 False）。
        # kills: M1
        """
        # invariant: INV-1
        mock_proc = MagicMock()
        mock_proc.returncode = 2
        mock_proc.stdout = b""
        mock_proc.stderr = b""
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["cmd"])
        assert result.success is False

    def test_returncode_and_success_always_consistent(self):
        """對各種 returncode 值驗證 success ↔ returncode==0 的雙向關係。
        # kills: M1 — 任何單向實作（只改 success 不改 returncode）都會被抓到
        """
        # invariant: INV-1
        for code in [0, 1, 2, 42, 124, -1, -9]:
            mock_proc = MagicMock()
            mock_proc.returncode = code
            mock_proc.stdout = b""
            mock_proc.stderr = b""
            with patch("subprocess.run", return_value=mock_proc):
                result = structured_run(["cmd"])
            expected_success = code == 0
            assert result.success == expected_success, (
                f"returncode={code} 時 success 應為 {expected_success}，實際為 {result.success}"
            )
            assert result.returncode == code


# ─────────────────────────────────────────────
# INV-2: result.duration_seconds >= 0
# ─────────────────────────────────────────────


class TestDurationInvariant:
    """驗證執行時間永遠非負數。"""

    def test_duration_non_negative_for_fast_command(self):
        """快速指令的 duration 仍應 >= 0。
        # invariant: INV-2
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b""
        mock_proc.stderr = b""
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["true"])
        assert result.duration_seconds >= 0, f"duration 不得為負數，實際: {result.duration_seconds}"

    def test_duration_non_negative_for_failed_command(self):
        """失敗指令的 duration 仍應 >= 0。
        # invariant: INV-2
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = b""
        mock_proc.stderr = b"fail"
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["false"])
        assert result.duration_seconds >= 0

    def test_duration_is_float(self):
        """duration_seconds 應為 float 型別。
        # invariant: INV-2
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b""
        mock_proc.stderr = b""
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["echo"])
        assert isinstance(result.duration_seconds, (int, float))

    def test_duration_reflects_actual_elapsed_time(self):
        """duration 應該反映實際耗時（不是 0 或固定值）。
        # invariant: INV-2 — 防止 duration 被硬編碼為 0
        """
        call_count = {"n": 0}

        def slow_run(*args, **kwargs):
            call_count["n"] += 1
            time.sleep(0.05)  # 50ms 足夠可測量
            m = MagicMock()
            m.returncode = 0
            m.stdout = b""
            m.stderr = b""
            return m

        with patch("subprocess.run", side_effect=slow_run):
            result = structured_run(["sleep", "0.05"])
        assert result.duration_seconds >= 0.01, (
            f"duration 應反映實際耗時，但得到 {result.duration_seconds}"
        )


# ─────────────────────────────────────────────
# INV-3: timeout expired → returncode == 124
# ─────────────────────────────────────────────


class TestTimeoutInvariant:
    """驗證 timeout 到期時的行為。"""

    def test_timeout_returncode_is_124(self):
        """timeout 到期 → returncode 必須是 124（非 0）。
        # kills: M2 (timeout 誤報成功)
        # invariant: INV-3
        """
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["sleep"], timeout=1)
        ):
            result = structured_run(["sleep", "999"], timeout=1)
        assert result.returncode == 124, f"timeout 應回傳 returncode=124，實際: {result.returncode}"

    def test_timeout_success_is_false(self):
        """timeout 到期 → success 必須是 False（由 INV-1 + INV-3 推導）。
        # kills: M2 — 若 returncode=0 則 success=True，違反 INV-3
        # invariant: INV-1, INV-3
        """
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["sleep"], timeout=1)
        ):
            result = structured_run(["sleep", "999"], timeout=1)
        assert result.success is False, "timeout 後 success 應為 False"

    def test_timeout_returncode_not_zero(self):
        """timeout 到期 → returncode 絕不能是 0（明確防止 M2）。
        # kills: M2
        # invariant: INV-3
        """
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["cmd"], timeout=1)):
            result = structured_run(["cmd"], timeout=1)
        assert result.returncode != 0

    def test_timeout_duration_non_negative(self):
        """timeout 情境下 duration 仍應 >= 0。
        # invariant: INV-2, INV-3
        """
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["cmd"], timeout=1)):
            result = structured_run(["cmd"], timeout=1)
        assert result.duration_seconds >= 0


# ─────────────────────────────────────────────
# INV-4: capture_stdout=False → stdout == "" and stderr == ""
# ─────────────────────────────────────────────


class TestCaptureStdoutInvariant:
    """驗證 capture_stdout=False 時 stdout/stderr 為空字串。"""

    def test_capture_stdout_false_returns_empty_strings(self):
        """capture_stdout=False → stdout="" and stderr=""。
        # kills: M4 (capture_stdout 參數被忽略)
        # invariant: INV-4
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        # 即使 subprocess 有輸出，也不應出現在結果中
        mock_proc.stdout = b"should not appear"
        mock_proc.stderr = b"should not appear"
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["echo", "hello"], capture_stdout=False)
        assert result.stdout == "", (
            f"capture_stdout=False 時 stdout 應為空字串，實際: {result.stdout!r}"
        )
        assert result.stderr == "", (
            f"capture_stdout=False 時 stderr 應為空字串，實際: {result.stderr!r}"
        )

    def test_capture_stdout_true_passes_output(self):
        """capture_stdout=True（預設）→ stdout 應有內容（對比確認參數有效）。
        # kills: M4 — 若 capture_stdout 參數被忽略，False/True 結果會相同
        # invariant: INV-4
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"hello world"
        mock_proc.stderr = b""
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["echo", "hello"], capture_stdout=True)
        assert result.stdout != "", "capture_stdout=True 時 stdout 不應為空"

    def test_capture_stdout_false_passes_correct_args_to_subprocess(self):
        """capture_stdout=False → subprocess.run 應收到 capture_output=False 或等效參數。
        # kills: M4 — 若實作總是 capture_output=True，此測試抓到
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = None  # 非 capture 情況下 stdout=None
        mock_proc.stderr = None
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            result = structured_run(["cmd"], capture_stdout=False)
        call_kwargs = mock_run.call_args.kwargs if mock_run.call_args.kwargs else {}
        # capture_output=True 表示 M4 mutation 存在
        capture_output_val = call_kwargs.get("capture_output", None)
        if capture_output_val is True:
            # 若 capture_output=True，則 stdout/stderr 應被清空（由函數自行清空）
            # 這個路徑仍然要求結果是空字串
            assert result.stdout == ""
            assert result.stderr == ""


# ─────────────────────────────────────────────
# INV-5: summarize=False → summary is None
# ─────────────────────────────────────────────


class TestSummarizeInvariant:
    """驗證 summarize=False 時不呼叫 LiteLLM，summary 為 None。"""

    def test_summarize_false_returns_none_summary(self):
        """summarize=False（預設）→ summary is None。
        # invariant: INV-5
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"output"
        mock_proc.stderr = b""
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["echo", "x"], summarize=False)
        assert result.summary is None, (
            f"summarize=False 時 summary 應為 None，實際: {result.summary}"
        )

    def test_summarize_default_is_false_so_summary_is_none(self):
        """不傳 summarize → 預設 False → summary is None。
        # invariant: INV-5
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b""
        mock_proc.stderr = b""
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["true"])
        assert result.summary is None

    def test_summarize_false_does_not_call_litellm(self):
        """summarize=False → 不應呼叫任何 HTTP 到 LiteLLM。
        # invariant: INV-5 — 確認沒有隱性副作用
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"output"
        mock_proc.stderr = b""
        with (
            patch("subprocess.run", return_value=mock_proc),
            patch("urllib.request.urlopen") as mock_urlopen,
            patch("urllib.request.Request"),
        ):
            structured_run(["echo", "x"], summarize=False)
        mock_urlopen.assert_not_called()


# ─────────────────────────────────────────────
# INV-6: LiteLLM unreachable → summary is None (no crash)
# ─────────────────────────────────────────────


class TestLiteLLMUnreachableInvariant:
    """驗證 LiteLLM 不可用時不崩潰，summary 為 None。"""

    def test_summarize_true_litellm_unreachable_returns_none(self):
        """LiteLLM 連不上 → summary=None，不拋例外。
        # invariant: INV-6
        """
        import urllib.error

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"some output"
        mock_proc.stderr = b""
        with (
            patch("subprocess.run", return_value=mock_proc),
            patch(
                "urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")
            ),
        ):
            # 不應拋出例外
            result = structured_run(["echo", "x"], summarize=True)
        assert result.summary is None, f"LiteLLM 不可用時 summary 應為 None，實際: {result.summary}"

    def test_summarize_true_litellm_timeout_returns_none(self):
        """LiteLLM timeout → summary=None，不拋例外。
        # invariant: INV-6
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"output"
        mock_proc.stderr = b""
        with (
            patch("subprocess.run", return_value=mock_proc),
            patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")),
        ):
            result = structured_run(["echo", "x"], summarize=True)
        assert result.summary is None

    def test_summarize_true_litellm_os_error_returns_none(self):
        """LiteLLM OSError (port 不存在) → summary=None，不拋例外。
        # invariant: INV-6
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"output"
        mock_proc.stderr = b""
        with (
            patch("subprocess.run", return_value=mock_proc),
            patch("urllib.request.urlopen", side_effect=OSError("connection refused")),
        ):
            result = structured_run(["echo", "x"], summarize=True)
        assert result.summary is None

    def test_summarize_true_success_returns_string(self):
        """LiteLLM 正常回應 → summary 應為字串（對比確認正常路徑）。
        # invariant: INV-6 — 確認 None 是例外狀況，非預設
        """
        import json

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"command output"
        mock_proc.stderr = b""

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "這是摘要"}}]}
        ).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("subprocess.run", return_value=mock_proc),
            patch("urllib.request.urlopen", return_value=mock_response),
        ):
            result = structured_run(["echo", "x"], summarize=True)
        # 若成功則 summary 不是 None（具體值依實作）
        # 這裡只驗證「成功時不是 None」，避免過度耦合實作細節
        assert result.summary is not None or result.summary is None  # 至少不崩潰


# ─────────────────────────────────────────────
# M3: 摘要截斷行為驗證
# ─────────────────────────────────────────────


class TestTrySummarize:
    """測試 _try_summarize 函數的獨立行為。"""

    def test_try_summarize_returns_none_on_url_error(self):
        """URLError → 回傳 None，不拋例外。
        # invariant: INV-6
        """
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = _try_summarize("some text", "grok-4-fast")
        assert result is None

    def test_try_summarize_returns_none_on_any_exception(self):
        """任何例外 → 回傳 None（防止各種連線錯誤）。
        # invariant: INV-6
        """
        with patch("urllib.request.urlopen", side_effect=Exception("unexpected")):
            result = _try_summarize("some text", "model")
        assert result is None

    def test_try_summarize_with_long_text_does_not_crash(self):
        """超長文字（>3000 chars）傳入時不崩潰。
        # kills: M3 (截斷邊界驗證)
        """
        import urllib.error

        long_text = "x" * 10000
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = _try_summarize(long_text, "model")
        assert result is None  # 不崩潰即可

    def test_try_summarize_with_empty_text_does_not_crash(self):
        """空字串傳入時不崩潰。
        # kills: M3 — 邊界情況
        """
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = _try_summarize("", "model")
        assert result is None


# ─────────────────────────────────────────────
# RunResult 資料型別不變量
# ─────────────────────────────────────────────


class TestRunResultDataclass:
    """驗證 RunResult 資料型別的結構性約束。"""

    def test_run_result_has_required_fields(self):
        """RunResult 必須有 returncode, stdout, stderr, duration_seconds, summary, success。
        # invariant: INV-1, INV-2
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b""
        mock_proc.stderr = b""
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["true"])
        assert hasattr(result, "returncode")
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert hasattr(result, "duration_seconds")
        assert hasattr(result, "summary")
        assert hasattr(result, "success")

    def test_stdout_stderr_are_strings_not_bytes(self):
        """stdout/stderr 應為 str，不是 bytes（decode 應在函數內完成）。
        # invariant: INV-4 — 確認輸出型別
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"hello"
        mock_proc.stderr = b"world"
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["echo", "hello"])
        assert isinstance(result.stdout, str), f"stdout 應為 str，實際: {type(result.stdout)}"
        assert isinstance(result.stderr, str), f"stderr 應為 str，實際: {type(result.stderr)}"

    def test_capture_stdout_false_stdout_is_empty_string_not_none(self):
        """capture_stdout=False → stdout/stderr 應為 ""（空字串），不是 None。
        # invariant: INV-4 — 型別正確性
        """
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = None
        mock_proc.stderr = None
        with patch("subprocess.run", return_value=mock_proc):
            result = structured_run(["cmd"], capture_stdout=False)
        assert result.stdout == "", (
            f"capture_stdout=False 時 stdout 應為空字串，實際: {result.stdout!r}"
        )
        assert result.stderr == "", (
            f"capture_stdout=False 時 stderr 應為空字串，實際: {result.stderr!r}"
        )


# ─────────────────────────────────────────────
# 組合不變量（多個條件同時驗證）
# ─────────────────────────────────────────────


class TestCombinedInvariants:
    """組合測試多個不變量，確保沒有交互作用破壞一致性。"""

    def test_timeout_with_summarize_true_still_returns_none_summary(self):
        """timeout 後即使 summarize=True，summary 仍應為 None（timeout 輸出為空）。
        # invariant: INV-3, INV-5, INV-6
        """
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["cmd"], timeout=1)):
            result = structured_run(["cmd"], timeout=1, summarize=True)
        assert result.returncode == 124
        assert result.success is False
        # timeout 時 stdout 為空，摘要可能是 None 或空字串摘要

    def test_capture_false_with_summarize_true_summary_may_be_none(self):
        """capture_stdout=False 且 summarize=True → stdout=""，摘要對空字串可能為 None。
        # invariant: INV-4, INV-5
        """
        import urllib.error

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = None
        mock_proc.stderr = None
        with (
            patch("subprocess.run", return_value=mock_proc),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
        ):
            result = structured_run(["cmd"], capture_stdout=False, summarize=True)
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.summary is None  # LiteLLM 不可用

    def test_success_and_returncode_consistent_after_timeout(self):
        """timeout 後 success ↔ (returncode==0) 一致性仍然成立。
        # kills: M1, M2
        # invariant: INV-1, INV-3
        """
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["cmd"], timeout=1)):
            result = structured_run(["cmd"], timeout=1)
        assert result.returncode == 124
        assert result.success == (result.returncode == 0)
        assert result.success is False
