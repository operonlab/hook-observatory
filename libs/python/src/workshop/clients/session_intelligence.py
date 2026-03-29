"""Session Intelligence — cross-session analytics and insights.

Direct implementation SDK — reads from multiple data sources to compute analytics.
No external HTTP dependencies; uses only stdlib + filesystem + SQLite.

Usage:
    from workshop.clients.session_intelligence import SessionIntelligenceClient

    client = SessionIntelligenceClient()

    stats = client.session_stats(days=30)
    sessions = client.session_list(days=7)
    patterns = client.pattern_analysis(days=30)
    trends = client.productivity_trends(weeks=4)
    digest = client.weekly_digest()
    report = client.security_report(days=30)
"""

import json
import logging
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


class SessionIntelligenceClient:
    """Cross-session analytics: stats, trends, patterns, digests.

    Reads directly from:
    - ~/.claude/projects/**/*.jsonl  (Claude Code session files)
    - ~/.local/share/workshop/session_redactor.sqlite  (redaction records)

    Args:
        redactor_db: Path to the session_redactor SQLite database.
            Defaults to REDACTOR_DB_PATH env or standard location.
        projects_dir: Path to Claude Code projects directory.
            Defaults to ~/.claude/projects.
    """

    def __init__(
        self,
        redactor_db: str | None = None,
        projects_dir: str | None = None,
    ):
        self.redactor_db = redactor_db or os.environ.get(
            "REDACTOR_DB_PATH",
            os.path.expanduser("~/.local/share/workshop/session_redactor.sqlite"),
        )
        self.projects_dir = projects_dir or os.path.expanduser("~/.claude/projects")

    # ======================== Session Stats ========================

    def session_stats(self, days: int = 30) -> dict:
        """Aggregate session statistics over the past N days.

        Returns:
            dict with: total_sessions, total_messages, avg_session_length,
            total_size_bytes, sessions_by_day, active_projects, redaction_stats
        """
        sessions = self._scan_sessions(days=days)

        total_sessions = len(sessions)
        total_messages = sum(s["messages"] for s in sessions)
        total_size = sum(s["size_bytes"] for s in sessions)
        avg_length = round(total_messages / total_sessions, 1) if total_sessions else 0

        # Group by day
        sessions_by_day: dict[str, int] = defaultdict(int)
        for s in sessions:
            day = s["modified_at"][:10]  # YYYY-MM-DD
            sessions_by_day[day] += 1

        # Unique active projects
        active_projects = list({s["project"] for s in sessions})

        # Redaction stats from DB
        redaction_stats = self._redaction_summary(days=days)

        return {
            "period_days": days,
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "avg_session_length": avg_length,
            "total_size_bytes": total_size,
            "sessions_by_day": dict(sorted(sessions_by_day.items())),
            "active_projects": active_projects,
            "active_projects_count": len(active_projects),
            "redaction_stats": redaction_stats,
        }

    def session_list(
        self,
        days: int = 7,
        project: str | None = None,
        limit: int = 0,
    ) -> dict:
        """List recent sessions with metadata.

        Args:
            days: Look back N days.
            project: Filter by project directory name (partial match).
            limit: Max sessions to return (0 = all).

        Returns:
            dict with total_count and items (list of session dicts without file_path)
        """
        sessions = self._scan_sessions(days=days)

        if project:
            sessions = [s for s in sessions if project.lower() in s["project"].lower()]

        total_count = len(sessions)

        if limit > 0:
            sessions = sessions[:limit]

        # Enrich with redaction data
        redaction_map = self._redaction_by_session()
        for s in sessions:
            s["redactions"] = redaction_map.get(s["session_id"], 0)
            s.pop("file_path", None)

        return {"total_count": total_count, "items": sessions}

    # ======================== Patterns ========================

    def pattern_analysis(self, days: int = 30) -> dict:
        """Detect patterns in session usage.

        Returns:
            dict with: peak_hours (Counter), avg_daily_sessions,
            common_projects, session_length_distribution,
            redaction_hotspots
        """
        sessions = self._scan_sessions(days=days)

        if not sessions:
            return {
                "period_days": days,
                "peak_hours": {},
                "avg_daily_sessions": 0.0,
                "common_projects": [],
                "session_length_distribution": {},
                "redaction_hotspots": {},
            }

        # Peak hours (based on file modification time)
        hour_counter: Counter = Counter()
        for s in sessions:
            try:
                dt = datetime.fromisoformat(s["modified_at"])
                hour_counter[dt.hour] += 1
            except Exception:
                pass

        # Average daily sessions
        if days > 0:
            avg_daily = round(len(sessions) / days, 2)
        else:
            avg_daily = 0.0

        # Most common projects
        project_counter: Counter = Counter(s["project"] for s in sessions)
        common_projects = [
            {"project": p, "sessions": c} for p, c in project_counter.most_common(10)
        ]

        # Session length distribution (by message count buckets)
        length_dist: Counter = Counter()
        for s in sessions:
            msgs = s["messages"]
            if msgs == 0:
                bucket = "0"
            elif msgs <= 10:
                bucket = "1-10"
            elif msgs <= 30:
                bucket = "11-30"
            elif msgs <= 100:
                bucket = "31-100"
            else:
                bucket = "100+"
            length_dist[bucket] += 1

        # Redaction hotspots — which categories fire most
        redaction_hotspots = self._redaction_categories(days=days)

        return {
            "period_days": days,
            "peak_hours": dict(hour_counter.most_common(24)),
            "avg_daily_sessions": avg_daily,
            "common_projects": common_projects,
            "session_length_distribution": dict(length_dist),
            "redaction_hotspots": redaction_hotspots,
        }

    def productivity_trends(self, weeks: int = 4) -> dict:
        """Weekly productivity trends.

        Args:
            weeks: Number of weeks to analyze.

        Returns:
            dict with ISO week keys (YYYY-WNN), each containing:
            sessions_count, total_messages, avg_session_length,
            unique_projects, redactions_count
        """
        days = weeks * 7
        sessions = self._scan_sessions(days=days)

        # Redaction map keyed by week
        redaction_map = self._redaction_by_session()

        week_data: dict[str, dict] = defaultdict(
            lambda: {
                "sessions_count": 0,
                "total_messages": 0,
                "unique_projects": set(),
                "redactions_count": 0,
            }
        )

        for s in sessions:
            try:
                dt = datetime.fromisoformat(s["modified_at"])
                iso_year, iso_week, _ = dt.isocalendar()
                week_key = f"{iso_year}-W{iso_week:02d}"
            except Exception:
                continue

            wd = week_data[week_key]
            wd["sessions_count"] += 1
            wd["total_messages"] += s["messages"]
            wd["unique_projects"].add(s["project"])
            wd["redactions_count"] += redaction_map.get(s["session_id"], 0)

        # Convert sets to counts and compute avg
        result = {}
        for wk in sorted(week_data.keys()):
            wd = week_data[wk]
            sc = wd["sessions_count"]
            tm = wd["total_messages"]
            result[wk] = {
                "sessions_count": sc,
                "total_messages": tm,
                "avg_session_length": round(tm / sc, 1) if sc else 0.0,
                "unique_projects": len(wd["unique_projects"]),
                "redactions_count": wd["redactions_count"],
            }

        return result

    # ======================== Weekly Digest ========================

    def weekly_digest(self, week_offset: int = 0) -> dict:
        """Aggregate raw weekly statistics from session data.

        Returns structured numeric data (counts, percentages, rankings),
        NOT a natural-language summary. Use Skill/MCP layer to interpret
        these numbers into human-readable insights.

        Args:
            week_offset: 0 = current week, 1 = last week, etc.

        Returns:
            dict with: period, summary_stats, top_projects,
            security_report, notable_sessions, comparison_vs_previous_week
        """
        now = datetime.now(UTC)
        # Find the start of the target week (Monday)
        days_since_monday = now.weekday()
        target_monday = now - timedelta(days=days_since_monday + week_offset * 7)
        target_monday = target_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        target_sunday = target_monday + timedelta(days=6, hours=23, minutes=59, seconds=59)

        # Scan a broader range to cover both this week and previous week
        scan_days = (week_offset + 2) * 7 + 7
        all_sessions = self._scan_sessions(days=scan_days)

        def in_week(session: dict, start: datetime, end: datetime) -> bool:
            try:
                dt = datetime.fromisoformat(session["modified_at"])
                return start <= dt <= end
            except Exception:
                return False

        this_week_sessions = [s for s in all_sessions if in_week(s, target_monday, target_sunday)]

        prev_monday = target_monday - timedelta(days=7)
        prev_sunday = target_monday - timedelta(seconds=1)
        prev_week_sessions = [s for s in all_sessions if in_week(s, prev_monday, prev_sunday)]

        # Summary stats for target week
        total_sessions = len(this_week_sessions)
        total_messages = sum(s["messages"] for s in this_week_sessions)
        avg_length = round(total_messages / total_sessions, 1) if total_sessions else 0

        # Top projects
        proj_counter: Counter = Counter(s["project"] for s in this_week_sessions)
        top_projects = [{"project": p, "sessions": c} for p, c in proj_counter.most_common(5)]

        # Security: redactions this week
        redaction_map = self._redaction_by_session()
        week_redactions = sum(redaction_map.get(s["session_id"], 0) for s in this_week_sessions)

        # Notable sessions (longest by message count)
        notable = sorted(this_week_sessions, key=lambda s: s["messages"], reverse=True)[:5]

        # Comparison vs previous week
        prev_total = len(prev_week_sessions)
        prev_messages = sum(s["messages"] for s in prev_week_sessions)
        prev_redactions = sum(redaction_map.get(s["session_id"], 0) for s in prev_week_sessions)

        def pct_change(current: int | float, previous: int | float) -> str:
            if previous == 0:
                return "+100%" if current > 0 else "0%"
            change = round((current - previous) / previous * 100, 1)
            return f"+{change}%" if change >= 0 else f"{change}%"

        return {
            "period": {
                "week_offset": week_offset,
                "start": target_monday.isoformat(),
                "end": target_sunday.isoformat(),
                "iso_week": f"{target_monday.isocalendar()[0]}-W{target_monday.isocalendar()[1]:02d}",
            },
            "summary_stats": {
                "total_sessions": total_sessions,
                "total_messages": total_messages,
                "avg_session_length": avg_length,
                "unique_projects": len(set(s["project"] for s in this_week_sessions)),
                "total_redactions": week_redactions,
            },
            "top_projects": top_projects,
            "notable_sessions": [
                {
                    "session_id": s["session_id"],
                    "project": s["project"],
                    "messages": s["messages"],
                    "modified_at": s["modified_at"],
                }
                for s in notable
            ],
            "security_report": {
                "total_redactions": week_redactions,
                "categories": self._redaction_categories_for_sessions(
                    [s["session_id"] for s in this_week_sessions]
                ),
            },
            "comparison_vs_previous_week": {
                "sessions_change": pct_change(total_sessions, prev_total),
                "messages_change": pct_change(total_messages, prev_messages),
                "redactions_change": pct_change(week_redactions, prev_redactions),
                "previous_week_sessions": prev_total,
                "previous_week_messages": prev_messages,
            },
        }

    # ======================== Security Report ========================

    def security_report(self, days: int = 30) -> dict:
        """Security-focused report on sensitive data detection.

        Returns:
            dict with: total_redactions, categories_breakdown, trend_by_day,
            most_affected_projects, unprocessed_sessions
        """
        # Query redactor DB for category breakdown
        categories = self._redaction_categories(days=days)
        total_redactions = sum(categories.values())

        # Trend by day
        trend = self._redaction_trend_by_day(days=days)

        # Most affected projects
        affected = self._most_affected_projects(days=days)

        # Unscanned sessions: sessions not in redactor DB
        all_sessions = self._scan_sessions(days=days)
        processed_ids = set(
            r["session_id"]
            for r in self._query_redactor_db("SELECT session_id FROM processed_sessions")
        )
        unprocessed = [s for s in all_sessions if s["session_id"] not in processed_ids]

        return {
            "period_days": days,
            "total_redactions": total_redactions,
            "categories_breakdown": categories,
            "trend_by_day": trend,
            "most_affected_projects": affected,
            "unprocessed_sessions": {
                "count": len(unprocessed),
                "sessions": [
                    {
                        "session_id": s["session_id"],
                        "project": s["project"],
                        "messages": s["messages"],
                        "modified_at": s["modified_at"],
                    }
                    for s in unprocessed[:10]
                ],
            },
        }

    # ======================== Helper Methods ========================

    def _scan_sessions(self, days: int = 30) -> list[dict]:
        """Scan session files and return metadata sorted by modified_at desc."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        sessions = []
        projects_dir = Path(self.projects_dir)

        if not projects_dir.exists():
            log.debug("projects_dir not found: %s", projects_dir)
            return sessions

        for jsonl_file in projects_dir.rglob("*.jsonl"):
            try:
                stat = jsonl_file.stat()
            except OSError:
                continue

            mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            if mtime < cutoff:
                continue

            # Count lines (messages)
            try:
                with open(jsonl_file, encoding="utf-8", errors="replace") as f:
                    line_count = sum(1 for _ in f)
            except OSError:
                line_count = 0

            # Use st_birthtime (macOS) for creation time if available
            if hasattr(stat, "st_birthtime"):
                created_at = datetime.fromtimestamp(stat.st_birthtime, tz=UTC).isoformat()
            else:
                created_at = mtime.isoformat()

            sessions.append(
                {
                    "session_id": jsonl_file.stem,
                    "project": jsonl_file.parent.name,
                    "file_path": str(jsonl_file),
                    "size_bytes": stat.st_size,
                    "messages": line_count,
                    "modified_at": mtime.isoformat(),
                    "created_at": created_at,
                }
            )

        return sorted(sessions, key=lambda s: s["modified_at"], reverse=True)

    def _query_redactor_db(self, query: str, params: tuple = ()) -> list[dict]:
        """Query the redactor SQLite database.

        Returns empty list if DB doesn't exist or query fails.
        """
        if not os.path.exists(self.redactor_db):
            log.debug("redactor_db not found: %s", self.redactor_db)
            return []
        try:
            conn = sqlite3.connect(self.redactor_db)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            result = [dict(r) for r in rows]
            conn.close()
            return result
        except Exception as exc:
            log.debug("redactor_db query error: %s", exc)
            return []

    def _redaction_summary(self, days: int = 30) -> dict:
        """Total redactions and basic breakdown for the period."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = self._query_redactor_db(
            "SELECT SUM(redactions) as total FROM processed_sessions WHERE processed_at >= ?",
            (cutoff,),
        )
        total = rows[0]["total"] if rows and rows[0]["total"] is not None else 0
        categories = self._redaction_categories(days=days)
        return {
            "total": total,
            "categories": categories,
        }

    def _redaction_by_session(self) -> dict[str, int]:
        """Return mapping of session_id -> redaction count for all sessions."""
        rows = self._query_redactor_db("SELECT session_id, redactions FROM processed_sessions")
        return {r["session_id"]: (r["redactions"] or 0) for r in rows}

    def _redaction_categories(self, days: int = 30) -> dict[str, int]:
        """Aggregate redaction counts by category over the period."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = self._query_redactor_db(
            "SELECT categories FROM processed_sessions WHERE processed_at >= ? AND categories IS NOT NULL",
            (cutoff,),
        )
        category_totals: Counter = Counter()
        for row in rows:
            try:
                cats = json.loads(row["categories"])
                if isinstance(cats, dict):
                    for cat, count in cats.items():
                        category_totals[cat] += count
                elif isinstance(cats, list):
                    for cat in cats:
                        category_totals[str(cat)] += 1
            except Exception:
                pass
        return dict(category_totals.most_common())

    def _redaction_categories_for_sessions(self, session_ids: list[str]) -> dict[str, int]:
        """Aggregate redaction categories for a specific set of sessions."""
        if not session_ids:
            return {}
        placeholders = ",".join("?" * len(session_ids))
        rows = self._query_redactor_db(
            f"SELECT categories FROM processed_sessions WHERE session_id IN ({placeholders}) AND categories IS NOT NULL",
            tuple(session_ids),
        )
        category_totals: Counter = Counter()
        for row in rows:
            try:
                cats = json.loads(row["categories"])
                if isinstance(cats, dict):
                    for cat, count in cats.items():
                        category_totals[cat] += count
                elif isinstance(cats, list):
                    for cat in cats:
                        category_totals[str(cat)] += 1
            except Exception:
                pass
        return dict(category_totals.most_common())

    def _redaction_trend_by_day(self, days: int = 30) -> dict[str, int]:
        """Redaction count grouped by day."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = self._query_redactor_db(
            "SELECT processed_at, redactions FROM processed_sessions WHERE processed_at >= ?",
            (cutoff,),
        )
        by_day: Counter = Counter()
        for row in rows:
            try:
                day = str(row["processed_at"])[:10]
                by_day[day] += row["redactions"] or 0
            except Exception:
                pass
        return dict(sorted(by_day.items()))

    def _most_affected_projects(self, days: int = 30) -> list[dict]:
        """Projects with the most redactions."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = self._query_redactor_db(
            "SELECT project_dir, SUM(redactions) as total FROM processed_sessions "
            "WHERE processed_at >= ? GROUP BY project_dir ORDER BY total DESC LIMIT 10",
            (cutoff,),
        )
        return [{"project": r["project_dir"], "total_redactions": r["total"] or 0} for r in rows]

    def __repr__(self) -> str:
        return (
            f"SessionIntelligenceClient("
            f"redactor_db={self.redactor_db!r}, "
            f"projects_dir={self.projects_dir!r})"
        )
