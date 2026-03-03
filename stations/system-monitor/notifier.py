"""
System Monitor V2 Notifier — pressure alerts via file + macOS + Web Push notifications.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import redis

SCRIPT_DIR = Path(__file__).parent
logger = logging.getLogger("sysmon.notifier")

# Pressure levels ranked by severity
PRESSURE_RANK = {"normal": 0, "unknown": 0, "warning": 1, "critical": 2, "danger": 3}


class PressureNotifier:
    def __init__(self, config: dict | None = None):
        if config is None:
            config_path = SCRIPT_DIR / "config.json"
            config = json.loads(config_path.read_text()) if config_path.exists() else {}
        self.config = config
        notification = config.get("notification", {})
        self.enabled = notification.get("enabled", True)
        self.methods = notification.get("methods", ["file"])
        self.alert_dir = Path(
            config.get("output_dir", "~/.claude/data/system-monitor")
        ).expanduser() / "alerts"
        self.alert_dir.mkdir(parents=True, exist_ok=True)
        self._last_pressure = "normal"  # Track pressure level to only push on escalation
        self._redis_url = os.environ.get("SYSMON_REDIS_URL", "redis://localhost:6379/0")

    def check_and_alert(self, data: dict) -> list[dict]:
        """Check pressure levels and send alerts if >= warning.

        Returns list of alert dicts that were triggered.
        """
        if not self.enabled:
            return []

        alerts = []
        overall = data.get("pressure_level", "normal")

        if PRESSURE_RANK.get(overall, 0) < 1:
            return []

        # Collect all subsystem pressures
        disk = data.get("disk", {})
        if PRESSURE_RANK.get(disk.get("pressure", "normal"), 0) >= 1:
            alerts.append({
                "subsystem": "disk",
                "pressure": disk["pressure"],
                "detail": f"磁碟使用率 {disk.get('usage_pct', '?')}%，"
                          f"可用 {disk.get('free_gb', '?')} GB",
            })

        hw = data.get("hardware", {})
        for key, label in [
            ("cpu", "CPU"),
            ("memory", "記憶體"),
            ("swap", "Swap"),
            ("temperature", "溫度"),
            ("battery", "電池"),
        ]:
            sub = hw.get(key, {})
            p = sub.get("pressure", "normal")
            if PRESSURE_RANK.get(p, 0) >= 1:
                detail = self._format_detail(key, sub)
                alerts.append({
                    "subsystem": key,
                    "pressure": p,
                    "detail": f"{label} — {detail}",
                })

        if not alerts:
            return []

        timestamp = datetime.now(UTC).isoformat()

        # Dispatch to configured methods
        if "file" in self.methods:
            self._alert_file(alerts, timestamp, overall)
        if "macos" in self.methods:
            self._alert_macos(alerts, overall)

        # Web Push: only on pressure ESCALATION (normal→warning, warning→critical, etc.)
        prev_rank = PRESSURE_RANK.get(self._last_pressure, 0)
        curr_rank = PRESSURE_RANK.get(overall, 0)
        if curr_rank > prev_rank:
            self._alert_push(alerts, overall)
        self._last_pressure = overall

        return alerts

    def _format_detail(self, key: str, sub: dict) -> str:
        if key == "cpu":
            return f"使用率 {sub.get('usage_pct', '?')}%"
        if key == "memory":
            return f"使用率 {sub.get('usage_pct', '?')}%, 已用 {sub.get('used_gb', '?')} GB"
        if key == "swap":
            return f"已用 {sub.get('used_gb', '?')} GB"
        if key == "temperature":
            temp = sub.get("cpu_temp_c")
            return f"{temp}°C" if temp else "不可用"
        if key == "battery":
            return f"{sub.get('percent', '?')}%"
        return str(sub)

    def _alert_file(self, alerts: list[dict], timestamp: str, overall: str) -> None:
        """Write alert to JSON file."""
        date_str = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
        alert_data = {
            "timestamp": timestamp,
            "overall_pressure": overall,
            "alerts": alerts,
        }
        path = self.alert_dir / f"alert-{date_str}.json"
        path.write_text(json.dumps(alert_data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _alert_macos(self, alerts: list[dict], overall: str) -> None:
        """Send macOS notification via terminal-notifier or osascript."""
        summary = ", ".join(a["detail"] for a in alerts[:3])
        title = f"System Monitor: {overall.upper()}"

        # Try terminal-notifier first
        if shutil.which("terminal-notifier"):
            try:
                subprocess.run(
                    [
                        "terminal-notifier",
                        "-title", title,
                        "-message", summary,
                        "-group", "system-monitor",
                    ],
                    capture_output=True, timeout=10,
                )
                return
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        # Fallback: osascript
        try:
            safe_summary = summary.replace("\\", "\\\\").replace('"', '\\"')
            safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
            script = f'display notification "{safe_summary}" with title "{safe_title}"'
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    def _alert_push(self, alerts: list[dict], overall: str) -> None:
        """Publish Web Push notification via Redis Pub/Sub."""
        summary = ", ".join(a["detail"] for a in alerts[:3])
        severity_map = {"warning": "warning", "critical": "critical", "danger": "critical"}
        payload = {
            "category": "system",
            "title": f"系統壓力: {overall.upper()}",
            "body": summary,
            "url": "/v2/apps/sysmon/",
            "tag": "system-pressure",
            "severity": severity_map.get(overall, "warning"),
        }
        try:
            r = redis.Redis.from_url(self._redis_url, decode_responses=True)
            r.publish("workshop:push", json.dumps(payload, ensure_ascii=False))
            r.close()
        except Exception as e:
            logger.warning("Failed to publish push notification: %s", e)
