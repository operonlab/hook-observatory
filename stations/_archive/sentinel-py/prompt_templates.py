"""Repair prompt templates for claude -p auto-remediation."""

from __future__ import annotations

SYSTEM_CONTEXT = """You are a Workshop infrastructure repair agent.
Your job is to diagnose and fix the failed service.
- Work in /Users/joneshong/workshop/
- Check logs at /opt/homebrew/var/log/workshop/{service}/
- Use workshop-services.sh for service management
- Do NOT modify application code — only restart/rebuild/reconfigure
- Report what you found and what you did"""

TEMPLATES: dict[str, str] = {
    "core": """Service 'core' (port 10000) is unhealthy.
Failure: {detail}

Steps:
1. Check logs: tail -50 /opt/homebrew/var/log/workshop/core/$(date +%Y-%m-%d).log
2. Check if process is running: lsof -i :10000
3. Try restart: /Users/joneshong/workshop/scripts/workshop-services.sh restart core
4. Verify: curl -s http://127.0.0.1:10000/health
""",
    "frontend": """Frontend (Nginx serving /) is unhealthy.
Failure: {detail}

Steps:
1. Check nginx: nginx -t
2. Check if dist exists: ls -la /Users/joneshong/workshop/workbench/dist/index.html
3. If dist missing or broken, rebuild:
   cd /Users/joneshong/workshop/workbench && pnpm run build
4. Reload nginx: nginx -s reload
5. Verify: curl -s http://127.0.0.1/ | head -5
""",
    "frontend-memvault": """Frontend route /memvault/ is unhealthy.
Failure: {detail}

This is likely the same issue as the main frontend. Check:
1. curl -s http://127.0.0.1/ (main page)
2. If main page also fails → rebuild frontend
3. If main page works but memvault fails → check React router config
""",
    "hook-observatory": """Hook Observatory (port 10100) is unhealthy.
Failure: {detail}

Steps:
1. Check logs: tail -50 /opt/homebrew/var/log/workshop/hook-observatory/$(date +%Y-%m-%d).log
2. Check process: lsof -i :10100
3. Restart: /Users/joneshong/workshop/scripts/workshop-services.sh restart hook-observatory
4. Verify: curl -s http://127.0.0.1:10100/
""",
    "postgres": """PostgreSQL container is unhealthy.
Failure: {detail}

Steps:
1. Check container: docker ps -a | grep postgres
2. Check logs: docker logs ws-infra-postgres-1 --tail 50
3. Restart: docker restart ws-infra-postgres-1
4. Wait 5s, verify: docker exec ws-infra-postgres-1 pg_isready
""",
    "redis": """Redis container is unhealthy.
Failure: {detail}

Steps:
1. Check container: docker ps -a | grep redis
2. Check logs: docker logs ws-infra-redis-1 --tail 50
3. Restart: docker restart ws-infra-redis-1
4. Verify: docker exec ws-infra-redis-1 redis-cli ping
""",
    "rustfs": """RustFS (MinIO fork, port 9000) is unhealthy.
Failure: {detail}

Steps:
1. Check container: docker ps -a | grep rustfs
2. Restart: docker restart ws-infra-rustfs-1
3. Verify: curl -s http://127.0.0.1:9000/
""",
}

# Generic fallback for unknown services
GENERIC_TEMPLATE = """Service '{service}' is unhealthy.
Failure: {detail}

Steps:
1. Check if the process is running
2. Check logs in /opt/homebrew/var/log/workshop/{service}/
3. Try restarting via workshop-services.sh
4. Verify the health endpoint
"""


def build_repair_prompt(service: str, detail: str) -> str:
    """Build a complete repair prompt for claude -p."""
    template = TEMPLATES.get(service, GENERIC_TEMPLATE)
    body = template.format(service=service, detail=detail)
    return f"{SYSTEM_CONTEXT}\n\n{body}"
