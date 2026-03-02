"""Enhanced autocomplete engine with periodic scanning of Claude Code resources."""

import json
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger("tmux-webui")


# ── YAML frontmatter parser ──


def _parse_yaml_frontmatter(filepath: str) -> dict:
    """Extract YAML frontmatter from a markdown file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read(4096)

        result = {}
        if content.startswith("---"):
            end = content.find("\n---", 3)
            if end != -1:
                fm_text = content[3:end].strip()
                lines = fm_text.split("\n")
                i = 0
                while i < len(lines):
                    line = lines[i]
                    if ":" in line and not line.startswith(" "):
                        key, _, val = line.partition(":")
                        val = val.strip().strip('"').strip("'")
                        # Handle YAML block scalars (>-, >, |-, |)
                        if val in (">-", ">", "|-", "|"):
                            parts = []
                            i += 1
                            while i < len(lines) and (
                                lines[i].startswith("  ") or lines[i].strip() == ""
                            ):
                                parts.append(lines[i].strip())
                                i += 1
                            result[key.strip()] = " ".join(
                                p for p in parts if p
                            )
                            continue
                        else:
                            result[key.strip()] = val
                    i += 1
                body = content[end + 4 :].strip()
            else:
                body = content
        else:
            body = content

        if "name" not in result:
            for line in body.split("\n"):
                if line.startswith("# "):
                    result["name"] = line[2:].strip()
                    break

        if "description" not in result:
            for line in body.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("---"):
                    result["description"] = line[:120]
                    break

        return result
    except Exception:
        return {}


# ── Resource scanners ──


def _scan_skills() -> list[dict]:
    """Scan ~/.claude/skills/*/SKILL.md for skill info."""
    skills_dir = os.path.expanduser("~/.claude/skills")
    if not os.path.isdir(skills_dir):
        return []

    results = []
    try:
        for entry in sorted(os.listdir(skills_dir)):
            skill_md = os.path.join(skills_dir, entry, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue
            fm = _parse_yaml_frontmatter(skill_md)
            desc = fm.get("description", "")
            results.append({
                "name": entry,
                "display_name": fm.get("name", entry),
                "description": desc[:100] if desc else "",
                "type": "skill",
                "icon": "/",
            })
    except Exception as e:
        logger.debug("Failed to scan skills: %s", e)

    return results


def _scan_commands() -> list[dict]:
    """Scan ~/.claude/commands/*.md for command info."""
    commands_dir = os.path.expanduser("~/.claude/commands")
    if not os.path.isdir(commands_dir):
        return []

    results = []
    try:
        for entry in sorted(os.listdir(commands_dir)):
            if not entry.endswith(".md"):
                continue
            cmd_path = os.path.join(commands_dir, entry)
            fm = _parse_yaml_frontmatter(cmd_path)
            name = entry[:-3]
            desc = fm.get("description", "")
            results.append({
                "name": name,
                "display_name": fm.get("name", name),
                "description": desc[:100] if desc else "",
                "type": "command",
                "icon": "/",
            })
    except Exception as e:
        logger.debug("Failed to scan commands: %s", e)

    return results


def _scan_agents() -> list[dict]:
    """Scan ~/.claude/agents/*.md for agent info."""
    agents_dir = os.path.expanduser("~/.claude/agents")
    if not os.path.isdir(agents_dir):
        return []

    results = []
    try:
        for entry in sorted(os.listdir(agents_dir)):
            if not entry.endswith(".md"):
                continue
            agent_path = os.path.join(agents_dir, entry)
            fm = _parse_yaml_frontmatter(agent_path)
            name = entry[:-3]
            model = fm.get("model", "")
            max_turns = fm.get("maxTurns", "")
            desc_parts = []
            if model:
                desc_parts.append(model)
            if max_turns:
                desc_parts.append(f"max {max_turns} turns")
            results.append({
                "name": name,
                "display_name": fm.get("name", name),
                "description": ", ".join(desc_parts) if desc_parts else "",
                "type": "agent",
                "icon": "@",
            })
    except Exception as e:
        logger.debug("Failed to scan agents: %s", e)

    return results


def _scan_mcp_servers() -> list[dict]:
    """Read MCP server names from settings files."""
    servers = {}
    settings_paths = [
        os.path.expanduser("~/.claude/settings.json"),
        str(Path(__file__).resolve().parents[2] / ".mcp.json"),
    ]

    for path in settings_paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            mcp_servers = data.get("mcpServers", {})
            for name, config in mcp_servers.items():
                if name not in servers:
                    cmd = config.get("command", "")
                    servers[name] = {
                        "name": name,
                        "display_name": name,
                        "description": f"MCP: {cmd}" if cmd else "MCP server",
                        "type": "mcp",
                        "icon": "@",
                    }
        except Exception:
            continue

    return list(servers.values())


# ── Resource cache ──


class ResourceCache:
    """Cache for scanned Claude Code resources with periodic refresh."""

    def __init__(self, scan_interval: int = 300):
        self.scan_interval = scan_interval
        self.skills: list[dict] = []
        self.commands: list[dict] = []
        self.agents: list[dict] = []
        self.mcp_servers: list[dict] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def start_periodic_scan(self):
        self._scan()
        self._schedule_next()

    def _schedule_next(self):
        self._timer = threading.Timer(self.scan_interval, self._periodic)
        self._timer.daemon = True
        self._timer.start()

    def _periodic(self):
        self._scan()
        self._schedule_next()

    def force_refresh(self):
        self._scan()

    def _scan(self):
        skills = _scan_skills()
        commands = _scan_commands()
        agents = _scan_agents()
        mcp_servers = _scan_mcp_servers()
        with self._lock:
            self.skills = skills
            self.commands = commands
            self.agents = agents
            self.mcp_servers = mcp_servers
        logger.info(
            "Resource scan: %d skills, %d commands, %d agents, %d MCP servers",
            len(skills), len(commands), len(agents), len(mcp_servers),
        )

    def get_slash_items(self) -> list[dict]:
        with self._lock:
            return list(self.skills) + list(self.commands)

    def get_at_items(self) -> list[dict]:
        with self._lock:
            return list(self.agents) + list(self.mcp_servers)


_cache = ResourceCache()


# ── Path completion ──


def complete_path(partial: str, max_results: int = 15) -> list[dict]:
    """Complete filesystem paths."""
    expanded = os.path.expanduser(partial)

    if os.path.isdir(expanded) and not partial.endswith("/"):
        expanded += "/"

    if expanded.endswith("/"):
        base_dir = expanded
        prefix = ""
    else:
        base_dir = os.path.dirname(expanded) or "."
        prefix = os.path.basename(expanded).lower()

    results = []
    try:
        entries = os.listdir(base_dir)
        for entry in sorted(entries):
            if entry.startswith(".") and not prefix.startswith("."):
                continue
            if prefix and not entry.lower().startswith(prefix):
                continue
            full = os.path.join(base_dir, entry)
            is_dir = os.path.isdir(full)
            display = entry + ("/" if is_dir else "")
            if expanded.endswith("/"):
                completed = partial + display
            else:
                completed = os.path.join(os.path.dirname(partial) or "", display)
                if partial.startswith("~/"):
                    completed = "~/" + os.path.relpath(full, os.path.expanduser("~"))
                    if is_dir:
                        completed += "/"
            results.append({
                "name": completed,
                "display_name": display,
                "description": "directory" if is_dir else "file",
                "type": "path",
                "icon": "/",
            })
            if len(results) >= max_results:
                break
    except (PermissionError, FileNotFoundError):
        pass

    return results


# ── Fuzzy matching ──


def _fuzzy_score(query: str, text: str) -> int:
    """Score a fuzzy match. Returns -1 for no match."""
    q = query.lower()
    t = text.lower()

    if not q:
        return 100

    if t.startswith(q):
        return 1000 - len(t)

    if q in t:
        return 500 - t.index(q)

    qi = 0
    score = 0
    for ch in t:
        if qi < len(q) and ch == q[qi]:
            qi += 1
            score += 1

    return score if qi == len(q) else -1


def _rank_and_filter(items: list[dict], query: str, max_results: int = 15) -> list[dict]:
    """Filter and rank items by fuzzy match score."""
    if not query:
        return items[:max_results]

    scored = []
    for item in items:
        score = _fuzzy_score(query, item["name"])
        if score >= 0:
            scored.append((score, item))

    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:max_results]]


# ── Public API ──


def init_cache():
    """Initialize the resource cache with periodic scanning."""
    _cache.start_periodic_scan()


def refresh_cache():
    """Force refresh the cache."""
    _cache.force_refresh()


def get_cache_stats() -> dict:
    """Get cache statistics."""
    with _cache._lock:
        return {
            "skills": len(_cache.skills),
            "commands": len(_cache.commands),
            "agents": len(_cache.agents),
            "mcp_servers": len(_cache.mcp_servers),
        }


def complete(query: str, type_filter: str = "") -> list[dict]:
    """Route completion based on trigger and type filter.

    type_filter: "slash" for / items, "at" for @ items, "path" for paths
    """
    query = query.strip()
    if not query:
        return []

    if type_filter == "slash" or (not type_filter and query.startswith("/")):
        search = query.lstrip("/")
        items = _cache.get_slash_items()
        return _rank_and_filter(items, search)

    if type_filter == "at" or (not type_filter and query.startswith("@")):
        search = query.lstrip("@")
        items = _cache.get_at_items()
        return _rank_and_filter(items, search)

    if type_filter == "path" or (
        not type_filter and query.startswith(("~", "./"))
    ):
        return complete_path(query)

    if "/" in query:
        return complete_path(query)

    return []
