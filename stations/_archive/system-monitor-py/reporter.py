"""
System Monitor V2 Reporter — AI-powered system report generation.

Three-layer LLM routing:
  1. LiteLLM API (http://localhost:4000) — fast, cheap, master_key auth
  2. Gemini CLI fallback — preferred by user (AfterAgent hook guarded)
  3. Gemini REST API — direct HTTP, no CLI dependency
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

WEEKLY_PROMPT = """\
你是 macOS 系統管理助手。以下是使用者電腦的完整系統數據（磁碟 + 硬體）。

請產生一份**週報**（中文），格式為 Markdown，包含：

1. **系統概述**：一句話總結整體健康狀態
2. **磁碟狀態**：用量百分比、可用空間、APFS 卷冊分布、最大目錄
3. **硬體狀態**：CPU/RAM/Swap/溫度/電池，標註異常指標
4. **壓力評估**：綜合壓力等級及說明
5. **建議行動**：最多 5 項具體操作，按優先順序排列，附清理指令

風險分級：🟢 安全 / 🟡 需確認 / 🔴 不要動
報告標題：# 系統週報 {date}

以下是收集到的數據：

{data}
"""

MONTHLY_PROMPT = """\
你是資深 macOS 系統管理員。以下是使用者電腦的完整系統數據（磁碟 + 硬體）。

請產生一份詳盡的**月報**（中文），格式為 Markdown，包含：

1. **系統健康總覽**：整體壓力等級、健康等級 🟢良好 / 🟡注意 / 🔴警告
2. **磁碟深度分析**：
   - APFS 卷冊分布與異常增長
   - Top 大檔案分析（類型、用途推測、風險等級）
   - 長期未使用檔案（按類別分組）
   - 快取清理建議（含指令與預估釋放空間）
3. **硬體趨勢**：CPU/RAM/Swap/溫度/電池，識別異常模式
4. **月度清理計畫**：最多 10 項操作，含指令、預估釋放空間、風險等級
5. **系統建議**：容量規劃、外接儲存評估、預防性建議

風險分級：
- 🟢 安全刪除：快取、暫存、安裝程式、備份副本
- 🟡 需確認：個人文件、專案檔、不確定用途的大檔案
- 🔴 不要動：系統檔案、.app bundle、~/.claude/*、~/.ssh/*

禁止建議刪除：/System/*、/Library/*、~/.claude/*、~/.ssh/*、~/.gnupg/*

報告標題：# 系統月報 {date}

以下是收集到的數據：

{data}
"""

PROMPTS = {
    "weekly": WEEKLY_PROMPT,
    "monthly": MONTHLY_PROMPT,
}


# ---------------------------------------------------------------------------
# LLM routing
# ---------------------------------------------------------------------------


def _call_litellm(prompt: str, config: dict) -> str | None:
    """Call LiteLLM-compatible API (with master_key auth)."""
    import urllib.error
    import urllib.request

    url = config.get("litellm_url", "http://localhost:4000")
    model = config.get("litellm_model", "gemini/gemini-2.5-flash")
    timeout = config.get("timeout_seconds", 120)
    master_key = os.environ.get("LITELLM_MASTER_KEY", "")

    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 4096,
        }
    ).encode()

    headers = {"Content-Type": "application/json"}
    if master_key:
        headers["Authorization"] = f"Bearer {master_key}"

    req = urllib.request.Request(
        f"{url}/v1/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
            return body["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError):
        return None


def _call_gemini_cli(prompt: str, config: dict) -> str | None:
    """Fallback 1: Gemini CLI (voice_notify Guard 0 blocks AfterAgent TTS)."""
    import subprocess

    cli = config.get("fallback_cli", "gemini")
    timeout = config.get("timeout_seconds", 120)

    try:
        r = subprocess.run(
            [cli, "-p", prompt, "-m", "gemini-2.5-flash"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _call_gemini_api(prompt: str, config: dict) -> str | None:
    """Fallback 2: Gemini REST API direct (no CLI dependency)."""
    import urllib.error
    import urllib.request

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None

    model = config.get("gemini_model", "gemini-2.5-flash")
    timeout = config.get("timeout_seconds", 120)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    payload = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096},
        }
    ).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
            return body["candidates"][0]["content"]["parts"][0]["text"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError):
        return None


# ---------------------------------------------------------------------------
# SystemReporter
# ---------------------------------------------------------------------------


class SystemReporter:
    def __init__(self, config: dict | None = None):
        if config is None:
            config_path = SCRIPT_DIR / "config.json"
            config = json.loads(config_path.read_text()) if config_path.exists() else {}
        self.config = config
        self.llm_config = config.get("llm", {})
        self.output_dir = Path(
            config.get("reports", {}).get("output_dir", "~/.claude/data/system-monitor/reports")
        ).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, data: dict, report_type: str = "weekly") -> str:
        """Generate an AI-powered system report.

        Args:
            data: collector.py JSON output
            report_type: "weekly" or "monthly"

        Returns:
            Path to the generated report file.
        """
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        template = PROMPTS.get(report_type, PROMPTS["weekly"])
        prompt = template.format(
            date=today,
            data=json.dumps(data, indent=2, ensure_ascii=False),
        )

        # Dual-layer LLM routing
        report_content = _call_litellm(prompt, self.llm_config)
        engine = "litellm"

        if not report_content:
            report_content = _call_gemini_cli(prompt, self.llm_config)
            engine = "gemini-cli"

        if not report_content:
            report_content = _call_gemini_api(prompt, self.llm_config)
            engine = "gemini-api"

        if not report_content:
            report_content = self._offline_report(data, report_type, today)
            engine = "offline"

        # Append metadata footer
        report_content += (
            f"\n\n---\n"
            f"*報告類型：{report_type} | 分析引擎：{engine} | "
            f"產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n"
        )

        # Write to file
        filename = f"{today}-{report_type}.md"
        out_path = self.output_dir / filename
        out_path.write_text(report_content, encoding="utf-8")

        return str(out_path)

    def _offline_report(self, data: dict, report_type: str, date: str) -> str:
        """Structured raw-data report when LLM is unavailable."""
        type_label = {"weekly": "週報", "monthly": "月報"}.get(report_type, "報告")
        pressure = data.get("pressure_level", "unknown")

        lines = [
            f"# 系統{type_label} {date}（離線模式）",
            "",
            "> AI 分析服務不可用，以下為自動整理的原始數據。",
            "",
            f"## 綜合壓力等級：{pressure}",
            "",
        ]

        # Disk summary
        disk = data.get("disk", {})
        if disk:
            lines.extend(
                [
                    "## 磁碟狀態",
                    f"- 總容量：{disk.get('total_gb', '?')} GB",
                    f"- 已使用：{disk.get('used_gb', '?')} GB ({disk.get('usage_pct', '?')}%)",
                    f"- 可用：{disk.get('free_gb', '?')} GB",
                    f"- 壓力等級：{disk.get('pressure', '?')}",
                    "",
                ]
            )

        # Hardware summary
        hw = data.get("hardware", {})
        if hw:
            lines.append("## 硬體狀態")
            cpu = hw.get("cpu", {})
            if cpu:
                lines.append(f"- CPU：{cpu.get('usage_pct', '?')}% ({cpu.get('pressure', '?')})")
            mem = hw.get("memory", {})
            if mem:
                lines.append(f"- RAM：{mem.get('usage_pct', '?')}% ({mem.get('pressure', '?')})")
            swap = hw.get("swap", {})
            if swap:
                lines.append(f"- Swap：{swap.get('used_gb', '?')} GB ({swap.get('pressure', '?')})")
            lines.append("")

        lines.extend(
            [
                "## 完整數據",
                "```json",
                json.dumps(data, indent=2, ensure_ascii=False)[:3000],
                "```",
            ]
        )

        return "\n".join(lines)

    def cleanup_old_reports(self) -> int:
        """Remove reports older than retention period. Returns count deleted."""
        retention = self.config.get("reports", {}).get("retention", {})
        weekly_days = retention.get("weekly_days", 60)
        monthly_days = retention.get("monthly_days", 365)

        deleted = 0
        now = datetime.now()

        for f in self.output_dir.glob("*.md"):
            try:
                # Parse date from filename: YYYY-MM-DD-type.md
                parts = f.stem.rsplit("-", 1)
                if len(parts) != 2:
                    continue
                date_str, rtype = parts
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                max_days = monthly_days if rtype == "monthly" else weekly_days
                if (now - file_date).days > max_days:
                    f.unlink()
                    deleted += 1
            except (ValueError, OSError):
                continue

        return deleted


if __name__ == "__main__":
    from collector import collect_all, load_config

    config = load_config()
    data = collect_all(config)
    reporter = SystemReporter(config)

    report_type = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    path = reporter.generate(data, report_type)
    print(f"Report saved to {path}")
