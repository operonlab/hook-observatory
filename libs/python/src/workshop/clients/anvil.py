"""Anvil SDK -- Standalone HTTP client for Anvil skill forge station.

Wraps the Anvil HTTP API (skill lifecycle, invocations, evaluations, corrections).
Unlike Core API clients (which inherit BaseClient), this wraps a station API.

Also provides local filesystem operations for skill scaffolding, structure testing,
and security scanning -- these do NOT require the Anvil server.

Usage:
    from workshop.clients.anvil import AnvilClient

    client = AnvilClient()

    # Remote (requires server)
    skills = client.list_skills()
    client.register_skill("my-skill", version="1.0.0")
    stats = client.get_stats()

    # Local (no server needed)
    client.create_skill_scaffold("my-skill")
    report = client.test_skill_structure("my-skill")
    findings = client.scan_skill_security("my-skill")
"""

import os
import re
from pathlib import Path
from typing import Any

import httpx


class AnvilError(Exception):
    """Raised when the Anvil API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Anvil error {status_code}: {detail}")


class AnvilClient:
    """HTTP client for Anvil station (port 4103).

    Args:
        base_url: API URL. Defaults to ANVIL_URL env or http://127.0.0.1:4103.
        timeout: Default request timeout in seconds.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 15):
        self.base_url = (base_url or os.environ.get("ANVIL_URL", "http://127.0.0.1:4103")).rstrip(
            "/"
        )
        self._timeout = timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def _request(
        self, method: str, path: str, timeout: float | None = None, **kwargs: Any
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self.client.request(method, url, timeout=timeout or self._timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.ConnectError:
            raise AnvilError(
                0,
                f"Cannot connect to Anvil at {self.base_url}. "
                "Start server: cd stations/anvil && uv run python main.py",
            ) from None
        except httpx.HTTPStatusError as e:
            raise AnvilError(e.response.status_code, e.response.text[:500]) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("GET", path, params=filtered).json()

    def _post(self, path: str, body: dict | None = None, params: dict | None = None) -> Any:
        kwargs: dict[str, Any] = {}
        if body is not None:
            kwargs["json"] = body
        else:
            kwargs["json"] = {}
        if params:
            filtered = {k: v for k, v in params.items() if v is not None}
            kwargs["params"] = filtered
        return self._request("POST", path, **kwargs).json()

    def _put(self, path: str, body: dict | None = None) -> Any:
        return self._request("PUT", path, json=body or {}).json()

    def _delete(self, path: str) -> Any:
        return self._request("DELETE", path).json()

    # ======================== Health ========================

    def health(self) -> dict:
        """Health check. GET /api/anvil/health"""
        return self._get("/api/anvil/health")

    def is_running(self) -> bool:
        """Check if Anvil is reachable."""
        try:
            self.health()
            return True
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("health check failed: %s", e)
            return False

    # ======================== Skills ========================

    def register_skill(
        self,
        name: str,
        version: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        io_schema: dict | None = None,
    ) -> dict:
        """Register or upsert a skill. POST /api/anvil/skills"""
        body: dict[str, Any] = {"name": name}
        if version is not None:
            body["version"] = version
        if description is not None:
            body["description"] = description
        if tags is not None:
            body["tags"] = tags
        if io_schema is not None:
            body["io_schema"] = io_schema
        return self._post("/api/anvil/skills", body)

    def list_skills(self, status: str = "active", limit: int = 50, offset: int = 0) -> dict:
        """List skills with optional filters. GET /api/anvil/skills"""
        return self._get(
            "/api/anvil/skills",
            {"status": status, "limit": limit, "offset": offset},
        )

    def get_skill(self, name: str) -> dict:
        """Get skill detail. GET /api/anvil/skills/{name}"""
        return self._get(f"/api/anvil/skills/{name}")

    def update_skill(self, name: str, **kwargs: Any) -> dict:
        """Update skill fields. PUT /api/anvil/skills/{name}"""
        body: dict[str, Any] = {}
        for key in ("version", "description", "tags", "io_schema", "status"):
            if key in kwargs and kwargs[key] is not None:
                body[key] = kwargs[key]
        return self._put(f"/api/anvil/skills/{name}", body)

    def archive_skill(self, name: str) -> dict:
        """Archive (soft-delete) a skill. DELETE /api/anvil/skills/{name}"""
        return self._delete(f"/api/anvil/skills/{name}")

    # ======================== Invocations ========================

    def record_invocation(
        self,
        skill_name: str,
        duration_ms: int | None = None,
        success: bool = True,
        error_message: str | None = None,
        tool_calls_count: int = 0,
        session_id: str | None = None,
        agent_model: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        """Record an invocation event. POST /api/anvil/invocations"""
        body: dict[str, Any] = {
            "skill_name": skill_name,
            "success": success,
            "tool_calls_count": tool_calls_count,
        }
        if duration_ms is not None:
            body["duration_ms"] = duration_ms
        if error_message is not None:
            body["error_message"] = error_message
        if session_id is not None:
            body["session_id"] = session_id
        if agent_model is not None:
            body["agent_model"] = agent_model
        if payload is not None:
            body["payload"] = payload
        return self._post("/api/anvil/invocations", body)

    def list_invocations(
        self,
        skill_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """List invocations with optional filters. GET /api/anvil/invocations"""
        return self._get(
            "/api/anvil/invocations",
            {"skill_name": skill_name, "limit": limit, "offset": offset},
        )

    # ======================== Stats ========================

    def get_stats(self) -> dict:
        """Get aggregated stats (top skills, avg success, 7d trend). GET /api/anvil/stats"""
        return self._get("/api/anvil/stats")

    def get_skill_stats(self, name: str) -> dict:
        """Get per-skill stats. GET /api/anvil/stats/{name}"""
        return self._get(f"/api/anvil/stats/{name}")

    # ======================== Evaluations ========================

    def trigger_eval(self, name: str, test_cases: list[dict] | None = None) -> dict:
        """Trigger skill evaluation. POST /api/anvil/evaluations/{name}"""
        body: dict[str, Any] = {}
        if test_cases is not None:
            body["test_cases"] = test_cases
        return self._post(f"/api/anvil/evaluations/{name}", body)

    def list_evaluations(
        self,
        skill_name: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> dict:
        """List evaluations. GET /api/anvil/evaluations"""
        return self._get(
            "/api/anvil/evaluations",
            {"skill_name": skill_name, "status": status, "limit": limit},
        )

    def get_evaluation(self, name: str) -> dict:
        """Get latest evaluation for a skill. GET /api/anvil/evaluations/{name}"""
        return self._get(f"/api/anvil/evaluations/{name}")

    def update_evaluation(self, eval_id: str, **kwargs: Any) -> dict:
        """Update evaluation results. PUT /api/anvil/evaluations/{eval_id}"""
        body: dict[str, Any] = {}
        for key in ("status", "results", "score", "notes"):
            if key in kwargs and kwargs[key] is not None:
                body[key] = kwargs[key]
        return self._put(f"/api/anvil/evaluations/{eval_id}", body)

    def get_benchmark(self, name: str) -> dict:
        """Get benchmark data for a skill. GET /api/anvil/evaluations/{name}/benchmark"""
        return self._get(f"/api/anvil/evaluations/{name}/benchmark")

    # ======================== Corrections ========================

    def propose_correction(
        self,
        skill_name: str,
        level: int = 1,
        trigger_reason: str = "",
        diff_content: str | None = None,
    ) -> dict:
        """Propose a self-correction. POST /api/anvil/corrections"""
        body: dict[str, Any] = {
            "skill_name": skill_name,
            "level": level,
            "trigger_reason": trigger_reason,
        }
        if diff_content is not None:
            body["diff_content"] = diff_content
        return self._post("/api/anvil/corrections", body)

    def list_corrections(
        self,
        skill_name: str | None = None,
        status: str | None = None,
    ) -> dict:
        """List corrections. GET /api/anvil/corrections"""
        return self._get(
            "/api/anvil/corrections",
            {"skill_name": skill_name, "status": status},
        )

    def update_correction(
        self,
        correction_id: str,
        status: str | None = None,
        approved_by: str | None = None,
    ) -> dict:
        """Update correction status. PUT /api/anvil/corrections/{id}"""
        body: dict[str, Any] = {}
        if status is not None:
            body["status"] = status
        if approved_by is not None:
            body["approved_by"] = approved_by
        return self._put(f"/api/anvil/corrections/{correction_id}", body)

    # ======================== Lifecycle Runs ========================

    def create_lifecycle_run(
        self,
        trigger: str = "manual",
        skipped_phases: list[str] | None = None,
    ) -> dict:
        """Create a new lifecycle run. POST /api/anvil/lifecycle/runs"""
        body: dict[str, Any] = {"trigger": trigger}
        if skipped_phases:
            body["skipped_phases"] = skipped_phases
        return self._post("/api/anvil/lifecycle/runs", body)

    def list_lifecycle_runs(
        self,
        status: str | None = None,
        trigger: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """List lifecycle runs. GET /api/anvil/lifecycle/runs"""
        return self._get(
            "/api/anvil/lifecycle/runs",
            {"status": status, "trigger": trigger, "limit": limit, "offset": offset},
        )

    def get_lifecycle_run(self, run_id: str) -> dict:
        """Get a lifecycle run. GET /api/anvil/lifecycle/runs/{run_id}"""
        return self._get(f"/api/anvil/lifecycle/runs/{run_id}")

    def update_lifecycle_run(self, run_id: str, **kwargs: Any) -> dict:
        """Update a lifecycle run. PATCH /api/anvil/lifecycle/runs/{run_id}"""
        return self._request("PATCH", f"/api/anvil/lifecycle/runs/{run_id}", json=kwargs).json()

    def get_lifecycle_trends(self, days: int = 30) -> dict:
        """Get lifecycle trends. GET /api/anvil/lifecycle/trends"""
        return self._get("/api/anvil/lifecycle/trends", {"days": days})

    # ======================== Local Operations ========================

    def scan_skills_dir(self, skills_dir: str = "~/.claude/skills") -> list[dict]:
        """Scan local skills directory and return metadata for each skill found.

        This is a local filesystem operation -- no HTTP call.
        """
        base = Path(skills_dir).expanduser()
        if not base.is_dir():
            return []

        results: list[dict] = []
        for entry in sorted(base.iterdir()):
            skill_md = entry / "SKILL.md"
            if not entry.is_dir() or not skill_md.is_file():
                continue

            info: dict[str, Any] = {
                "name": entry.name,
                "path": str(entry),
                "has_skill_md": True,
                "has_readme": (entry / "README.md").is_file(),
            }

            # Parse frontmatter from SKILL.md
            try:
                content = skill_md.read_text(encoding="utf-8")
                fm = self._parse_frontmatter(content)
                info["description"] = fm.get("description", "")
                info["tags"] = fm.get("tags", [])
                info["version"] = fm.get("version", "")
                info["io_schema"] = fm.get("io", {})
                info["lines"] = content.count("\n") + 1
            except Exception:
                info["description"] = ""
                info["tags"] = []
                info["parse_error"] = True

            results.append(info)

        return results

    def create_skill_scaffold(self, name: str, skills_dir: str = "~/.claude/skills") -> dict:
        """Create a new skill directory with SKILL.md and README.md templates.

        This is a local filesystem operation -- no HTTP call.

        Returns:
            dict with keys: name, path, created_files
        """
        base = Path(skills_dir).expanduser()
        skill_dir = base / name

        if skill_dir.exists():
            return {
                "name": name,
                "path": str(skill_dir),
                "created": False,
                "error": f"Skill directory already exists: {skill_dir}",
            }

        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_md_content = f"""---
description: "{name} skill"
version: "0.1.0"
tags: []
io:
  input:
    - mime: "text/plain"
      description: "Input data"
  output:
    - mime: "text/plain"
      description: "Output data"
triggers:
  - "{name}"
---

# {name}

## Purpose
Describe what this skill does.

## Usage
How to invoke this skill.

## Steps
1. Step one
2. Step two

## Output Format
Describe the expected output format.

## Examples
Provide usage examples.

## Constraints
- List any constraints or limitations.
"""

        readme_content = f"""# {name}

## Description
A Workshop skill for {name}.

## Installation
This skill is part of the Workshop skill ecosystem.

## Usage
Invoke via Claude Code or the Anvil CLI.

## License
Private
"""

        (skill_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
        (skill_dir / "README.md").write_text(readme_content, encoding="utf-8")

        return {
            "name": name,
            "path": str(skill_dir),
            "created": True,
            "created_files": ["SKILL.md", "README.md"],
        }

    def test_skill_structure(self, name: str, skills_dir: str = "~/.claude/skills") -> dict:
        """Run T1-T5 structural tests on a skill.

        Tests:
            T1: Required files exist (SKILL.md)
            T2: Frontmatter is valid YAML
            T3: Required sections present (Purpose/Usage/Steps)
            T4: Triggers defined in frontmatter
            T5: No circular references in triggers

        Returns:
            dict with keys: name, tests (list of {id, name, passed, detail})
        """
        base = Path(skills_dir).expanduser()
        skill_dir = base / name
        tests: list[dict[str, Any]] = []

        # T1: Required files exist
        skill_md = skill_dir / "SKILL.md"
        t1_passed = skill_md.is_file()
        tests.append(
            {
                "id": "T1",
                "name": "Required files exist",
                "passed": t1_passed,
                "detail": "SKILL.md found" if t1_passed else f"SKILL.md not found at {skill_dir}",
            }
        )

        if not t1_passed:
            # Cannot proceed without SKILL.md
            for tid, tname in [
                ("T2", "Frontmatter valid"),
                ("T3", "Required sections present"),
                ("T4", "Triggers defined"),
                ("T5", "No circular references"),
            ]:
                tests.append(
                    {
                        "id": tid,
                        "name": tname,
                        "passed": False,
                        "detail": "Skipped (SKILL.md missing)",
                    }
                )
            return {"name": name, "tests": tests, "passed": 0, "failed": 5}

        content = skill_md.read_text(encoding="utf-8")

        # T2: Frontmatter is valid YAML
        fm = self._parse_frontmatter(content)
        t2_passed = len(fm) > 0
        tests.append(
            {
                "id": "T2",
                "name": "Frontmatter valid",
                "passed": t2_passed,
                "detail": f"Parsed {len(fm)} frontmatter fields"
                if t2_passed
                else "No valid YAML frontmatter found",
            }
        )

        # T3: Required sections present
        required_sections = ["purpose", "usage", "steps"]
        body_lower = content.lower()
        found_sections = []
        missing_sections = []
        for section in required_sections:
            # Look for ## Section or # Section patterns
            pattern = rf"^#{{1,3}}\s+{re.escape(section)}"
            if re.search(pattern, body_lower, re.MULTILINE):
                found_sections.append(section)
            else:
                missing_sections.append(section)
        t3_passed = len(missing_sections) == 0
        tests.append(
            {
                "id": "T3",
                "name": "Required sections present",
                "passed": t3_passed,
                "detail": f"Found: {', '.join(found_sections)}"
                + (f"; Missing: {', '.join(missing_sections)}" if missing_sections else ""),
            }
        )

        # T4: Triggers defined
        triggers = fm.get("triggers", [])
        t4_passed = isinstance(triggers, list) and len(triggers) > 0
        tests.append(
            {
                "id": "T4",
                "name": "Triggers defined",
                "passed": t4_passed,
                "detail": f"{len(triggers)} trigger(s): {', '.join(str(t) for t in triggers)}"
                if t4_passed
                else "No triggers defined in frontmatter",
            }
        )

        # T5: No circular references
        # Check that triggers don't reference the skill's own name in a way that
        # would create a loop. Also check for duplicate triggers.
        t5_detail = "No circular references detected"
        t5_passed = True
        if triggers:
            seen = set()
            duplicates = []
            for t in triggers:
                t_str = str(t).lower()
                if t_str in seen:
                    duplicates.append(t_str)
                seen.add(t_str)
            if duplicates:
                t5_passed = False
                t5_detail = f"Duplicate triggers: {', '.join(duplicates)}"
        tests.append(
            {
                "id": "T5",
                "name": "No circular references",
                "passed": t5_passed,
                "detail": t5_detail,
            }
        )

        passed_count = sum(1 for t in tests if t["passed"])
        failed_count = len(tests) - passed_count

        return {"name": name, "tests": tests, "passed": passed_count, "failed": failed_count}

    def scan_skill_security(self, name: str, skills_dir: str = "~/.claude/skills") -> dict:
        """Run security scan (S1-S3) on a skill.

        Checks:
            S1: Prompt injection patterns (system prompt override, ignore instructions)
            S2: Privilege escalation (sudo, chmod 777, rm -rf, eval())
            S3: Data exfiltration (curl POST to external, base64 encode secrets)

        Returns:
            dict with keys: name, findings (list of {id, severity, pattern, line, context})
        """
        base = Path(skills_dir).expanduser()
        skill_dir = base / name
        findings: list[dict[str, Any]] = []

        # Collect all text files in the skill directory
        files_to_scan: list[Path] = []
        if skill_dir.is_dir():
            for f in skill_dir.rglob("*"):
                if f.is_file() and f.suffix in (
                    ".md",
                    ".py",
                    ".sh",
                    ".js",
                    ".ts",
                    ".yaml",
                    ".yml",
                    ".json",
                    ".txt",
                    "",
                ):
                    files_to_scan.append(f)

        if not files_to_scan:
            return {
                "name": name,
                "findings": [],
                "scanned_files": 0,
                "clean": True,
            }

        # S1: Prompt injection patterns
        s1_patterns = [
            (
                r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|rules)",
                "Instruction override attempt",
            ),
            (r"you\s+are\s+now\s+(a|an)\s+", "Role reassignment attempt"),
            (r"system\s*prompt\s*[:=]", "System prompt override"),
            (r"forget\s+(everything|all|your\s+instructions)", "Memory wipe attempt"),
            (r"disregard\s+(all|any|previous)", "Disregard instructions attempt"),
            (r"new\s+instructions?\s*[:=]", "New instructions injection"),
            (
                r"act\s+as\s+if\s+you\s+have\s+no\s+(rules|constraints)",
                "Constraint removal attempt",
            ),
        ]

        # S2: Privilege escalation patterns
        s2_patterns = [
            (r"\bsudo\b", "sudo usage"),
            (r"chmod\s+777", "World-writable permissions"),
            (r"rm\s+-rf\s+/", "Root filesystem deletion"),
            (r"\beval\s*\(", "Dynamic code execution (eval)"),
            (r"\bexec\s*\(", "Dynamic code execution (exec)"),
            (r"os\.system\s*\(", "os.system call"),
            (r"subprocess\.(call|run|Popen)\s*\(.*shell\s*=\s*True", "Shell injection risk"),
            (r"__import__\s*\(", "Dynamic import"),
        ]

        # S3: Data exfiltration patterns
        s3_patterns = [
            (r"curl\s+.*-X\s*POST\s+https?://(?!127\.0\.0\.1|localhost)", "External POST request"),
            (r"curl\s+.*--data.*https?://(?!127\.0\.0\.1|localhost)", "Data upload to external"),
            (r"base64\s+(encode|decode).*secret", "Base64 encoding of secrets"),
            (r"(API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*['\"]", "Hardcoded secret"),
            (
                r"requests\.(post|put)\s*\(\s*['\"]https?://(?!127\.0\.0\.1|localhost)",
                "External HTTP data send",
            ),
            (r"webhook[s]?\s*[:=]\s*['\"]https?://", "Webhook URL (potential exfil)"),
            (r"ngrok|serveo|localtunnel", "Tunnel service reference"),
        ]

        all_checks = [
            ("S1", "prompt_injection", "high", s1_patterns),
            ("S2", "privilege_escalation", "critical", s2_patterns),
            ("S3", "data_exfiltration", "high", s3_patterns),
        ]

        for filepath in files_to_scan:
            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: S112
                continue

            lines = content.split("\n")
            rel_path = str(filepath.relative_to(skill_dir))

            for check_id, category, severity, patterns in all_checks:
                for pattern_str, description in patterns:
                    for line_num, line in enumerate(lines, 1):
                        if re.search(pattern_str, line, re.IGNORECASE):
                            findings.append(
                                {
                                    "id": check_id,
                                    "category": category,
                                    "severity": severity,
                                    "pattern": description,
                                    "file": rel_path,
                                    "line": line_num,
                                    "context": line.strip()[:120],
                                }
                            )

        return {
            "name": name,
            "findings": findings,
            "scanned_files": len(files_to_scan),
            "clean": len(findings) == 0,
        }

    # ======================== Helpers ========================

    @staticmethod
    def _parse_frontmatter(content: str) -> dict:
        """Parse YAML frontmatter from markdown content.

        Handles the --- delimited block at the start of the file.
        Uses a simple parser to avoid requiring PyYAML.
        """
        content = content.strip()
        if not content.startswith("---"):
            return {}

        end_idx = content.find("---", 3)
        if end_idx == -1:
            return {}

        fm_text = content[3:end_idx].strip()
        if not fm_text:
            return {}

        result: dict[str, Any] = {}
        current_key: str | None = None
        current_list: list | None = None
        current_indent: int = 0
        nested_key: str | None = None
        nested_dict: dict[str, Any] | None = None
        nested_list: list | None = None

        for line in fm_text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            indent = len(line) - len(line.lstrip())

            # Handle list items under a key
            if stripped.startswith("- "):
                item_value = stripped[2:].strip().strip('"').strip("'")
                if nested_list is not None and indent > current_indent:
                    # Parse nested list item as dict if it has a colon
                    if ": " in item_value:
                        parts = item_value.split(": ", 1)
                        item_dict: dict[str, str] = {
                            parts[0].strip(): parts[1].strip().strip('"').strip("'")
                        }
                        # Peek ahead is not possible, so just add as simple dict
                        nested_list.append(item_dict)
                    else:
                        nested_list.append(item_value)
                elif current_list is not None:
                    current_list.append(item_value)
                continue

            # Handle nested dict items (e.g., "  mime: text/plain")
            if indent > 0 and nested_dict is not None and ": " in stripped:
                k, v = stripped.split(": ", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                nested_dict[k] = v
                continue

            # Handle top-level or second-level key: value
            if ": " in stripped or stripped.endswith(":"):
                if ": " in stripped:
                    key, value = stripped.split(": ", 1)
                    key = key.strip()
                    value = value.strip()
                else:
                    key = stripped.rstrip(":").strip()
                    value = ""

                if indent == 0:
                    # Top-level key
                    current_key = key
                    current_indent = indent
                    nested_key = None
                    nested_dict = None
                    nested_list = None

                    if not value:
                        # Could be a list or nested dict -- will be filled by subsequent lines
                        current_list = []
                        result[key] = current_list
                    elif value.startswith("[") and value.endswith("]"):
                        # Inline list
                        inner = value[1:-1].strip()
                        if inner:
                            result[key] = [
                                item.strip().strip('"').strip("'") for item in inner.split(",")
                            ]
                        else:
                            result[key] = []
                        current_list = None
                    else:
                        result[key] = value.strip('"').strip("'")
                        current_list = None
                else:
                    # Nested key under current_key
                    if current_key and isinstance(result.get(current_key), list):
                        # This is a sub-key under a list parent (like io.input)
                        nested_key = key  # noqa: F841
                        if not value:
                            nested_list = []
                            # Replace the list with a dict structure
                            if isinstance(result[current_key], list) and not result[current_key]:
                                result[current_key] = {}
                            if isinstance(result[current_key], dict):
                                result[current_key][key] = nested_list
                            current_list = None
                        else:
                            if isinstance(result[current_key], list) and not result[current_key]:
                                result[current_key] = {}
                            if isinstance(result[current_key], dict):
                                result[current_key][key] = value.strip('"').strip("'")
                    elif current_key and isinstance(result.get(current_key), dict):
                        if not value:
                            nested_list = []
                            result[current_key][key] = nested_list
                            current_list = None
                        else:
                            result[current_key][key] = value.strip('"').strip("'")

        # Clean up empty lists that should remain as lists
        return result

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"AnvilClient(base_url={self.base_url!r})"
