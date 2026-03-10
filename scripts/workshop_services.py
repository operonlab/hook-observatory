#!/usr/bin/env python3
"""
Workshop Unified Service Launcher
Single entry point for all workshop daemon services.
"""

import gzip
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

# ── Daemon PATH (launchd does not inherit .zshenv) ─────────────
_DAEMON_PATH = "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Users/joneshong/.local/bin"
_DAEMON_ENV = {**dict(os.environ), "PATH": _DAEMON_PATH}

# ── Configuration ──────────────────────────────────────────────
LOG_BASE = Path("/opt/homebrew/var/log/workshop")
PID_DIR = Path("/opt/homebrew/var/run/workshop")
LOG_RETAIN_DAYS = 90
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10MB

# Service registry: list of dicts with name, type, cmd, port, health, workdir
SERVICES = [
    # ── V2 Core ──
    {
        "name": "core",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/.venv/bin/python3 -m uvicorn src.main:app --host 127.0.0.1 --port 8801 --env-file .env",
        "port": 8801,
        "health": "http://127.0.0.1:8801/docs",
        "workdir": "/Users/joneshong/workshop/core",
    },
    # ── Stations ──
    {
        "name": "agent-vista",
        "type": "binary",
        "cmd": "/Users/joneshong/workshop/stations/agent-vista/bin/agent-vista --no-browser --port 8840",
        "port": 8840,
        "health": "http://127.0.0.1:8840",
        "workdir": "/Users/joneshong/workshop/stations/agent-vista",
    },
    {
        "name": "hook-observatory",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/hook-observatory/.venv/bin/python3 main.py",
        "port": 4100,
        "health": "http://127.0.0.1:4100",
        "workdir": "/Users/joneshong/workshop/stations/hook-observatory",
    },
    {
        "name": "system-monitor",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/system-monitor/.venv/bin/python3 api.py --port 9526",
        "port": 9526,
        "health": "http://127.0.0.1:9526",
        "workdir": "/Users/joneshong/workshop/stations/system-monitor",
    },
    {
        "name": "agent-metrics",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/agent-metrics/.venv/bin/python3 -m agent_metrics serve",
        "port": 8795,
        "health": "http://127.0.0.1:8795/health",
        "workdir": "/Users/joneshong/workshop/stations/agent-metrics",
    },
    {
        "name": "auto-survey",
        "type": "uvicorn",
        "cmd": "/opt/homebrew/bin/uv run --project /Users/joneshong/workshop/stations/auto-survey auto-survey serve --host 127.0.0.1 --port 4102",
        "port": 4102,
        "health": "http://127.0.0.1:4102/api/people",
        "workdir": "/Users/joneshong/workshop/stations/auto-survey",
    },
    {
        "name": "anvil",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/anvil/.venv/bin/python3 -m uvicorn server:app --host 127.0.0.1 --port 4103",
        "port": 4103,
        "health": "http://127.0.0.1:4103/docs",
        "workdir": "/Users/joneshong/workshop/stations/anvil/src",
    },
    {
        "name": "tmux-webui",
        "type": "uvicorn",
        "cmd": "/opt/homebrew/bin/uv run /Users/joneshong/workshop/stations/tmux-webui/server.py --host 127.0.0.1 --port 8765",
        "port": 8765,
        "health": "http://127.0.0.1:8765",
        "workdir": "/Users/joneshong/workshop/stations/tmux-webui",
    },
    {
        "name": "capture-console",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/capture-console/.venv/bin/python3 -m uvicorn server:app --host 127.0.0.1 --port 4104",
        "port": 4104,
        "health": "http://127.0.0.1:4104/docs",
        "workdir": "/Users/joneshong/workshop/stations/capture-console",
    },
    {
        "name": "cronicle",
        "type": "binary",
        "cmd": "/opt/homebrew/bin/node /Users/joneshong/workshop/vendor/cronicle/lib/main.js",
        "port": 4105,
        "health": "http://127.0.0.1:4105/api/app/ping",
        "workdir": "/Users/joneshong/workshop/vendor/cronicle",
    },
    # ── Infrastructure Tools ──
    {
        "name": "mcpproxy",
        "type": "binary",
        "cmd": "/Users/joneshong/.local/bin/mcpproxy serve --listen 127.0.0.1:8808",
        "port": 8808,
        "health": "http://127.0.0.1:8808/health",
        "workdir": "/Users/joneshong",
    },
    {
        "name": "litellm",
        "type": "binary",
        "cmd": "/Users/joneshong/.local/bin/litellm --config /Users/joneshong/.config/litellm/config.yaml --port 4000 --host 127.0.0.1",
        "port": 4000,
        "health": "http://127.0.0.1:4000",
        "workdir": "/Users/joneshong",
    },
]

# Docker containers: name, port, health_cmd
DOCKER_CONTAINERS = [
    {
        "name": "ws-infra-postgres-1",
        "port": 5432,
        "health_cmd": ["docker", "exec", "ws-infra-postgres-1", "pg_isready"],
    },
    {
        "name": "ws-infra-redis-1",
        "port": 6379,
        "health_cmd": ["docker", "exec", "ws-infra-redis-1", "redis-cli", "ping"],
    },
    {
        "name": "ws-infra-rustfs-1",
        "port": 9000,
        "health_cmd": None,  # Uses HTTP check
        "health_url": "http://127.0.0.1:9000/",
    },
    {
        "name": "ws-infra-filebrowser-1",
        "port": 8850,
        "health_cmd": None,
        "health_url": "http://127.0.0.1:8850/apps/files/health",
    },
    {
        "name": "ws-infra-lgtm-1",
        "port": 3100,
        "health_cmd": None,
        "health_url": "http://127.0.0.1:3100/api/health",
    },
    {
        "name": "ws-infra-bark-1",
        "port": 8090,
        "health_cmd": None,
        "health_url": "http://127.0.0.1:8090/ping",
    },
    {
        "name": "ws-infra-ntfy-1",
        "port": 9080,
        "health_cmd": None,
        "health_url": "http://127.0.0.1:9080/v1/health",
    },
    {
        "name": "ws-infra-qdrant-1",
        "port": 6333,
        "health_cmd": None,
        "health_url": "http://127.0.0.1:6333/healthz",
    },
]

# ANSI color codes
GREEN = "\033[0;32m"
RED = "\033[0;31m"
RESET = "\033[0m"
CHECKMARK = "✓"
CROSS = "✗"


# ── Helpers ────────────────────────────────────────────────────


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def err(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] ERROR: {msg}", file=sys.stderr, flush=True)


def ensure_dirs() -> None:
    PID_DIR.mkdir(parents=True, exist_ok=True)
    for svc in SERVICES:
        (LOG_BASE / svc["name"]).mkdir(parents=True, exist_ok=True)
    (LOG_BASE / "launcher").mkdir(parents=True, exist_ok=True)


def is_running(name: str) -> int | None:
    """Return PID if service is running, else None.
    Detects zombie processes (state Z) as not running.
    """
    pidfile = PID_DIR / f"{name}.pid"
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)  # Test if process exists
            # Check for zombie: ps returns 'Z' state for defunct processes
            result = subprocess.run(
                ["ps", "-o", "state=", "-p", str(pid)],
                capture_output=True,
                text=True,
            )
            state = result.stdout.strip()
            if state.startswith("Z"):
                log(f"{name} (PID {pid}) is zombie — cleaning up")
                pidfile.unlink(missing_ok=True)
                return None
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            pidfile.unlink(missing_ok=True)
    return None


def wait_for_health(url: str, timeout: int, name: str) -> bool:
    """Poll health URL until it responds or timeout."""
    elapsed = 0
    while elapsed < timeout:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(2)
        elapsed += 2
    err(f"{name} health check failed after {timeout}s (url: {url})")
    return False


# ── Docker ─────────────────────────────────────────────────────


def wait_for_docker(timeout: int = 120) -> bool:
    log("Waiting for Docker Desktop...")
    elapsed = 0
    while elapsed < timeout:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
        )
        if result.returncode == 0:
            log("Docker is ready.")
            return True
        time.sleep(5)
        elapsed += 5
    err(f"Docker Desktop not ready after {timeout}s")
    return False


def ensure_containers() -> None:
    for container in DOCKER_CONTAINERS:
        name = container["name"]
        port = container["port"]

        # Check if running
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
        )
        state = result.stdout.strip() if result.returncode == 0 else "false"

        if state != "true":
            log(f"Starting container: {name}")
            start_result = subprocess.run(
                ["docker", "start", name],
                capture_output=True,
            )
            if start_result.returncode != 0:
                err(f"Failed to start {name}")
                continue

        log(f"Checking health: {name} (:{port})")
        timeout = 30
        elapsed = 0
        healthy = False

        while elapsed < timeout:
            if container.get("health_cmd"):
                result = subprocess.run(
                    container["health_cmd"],
                    capture_output=True,
                )
                if result.returncode == 0:
                    healthy = True
                    break
            elif container.get("health_url"):
                try:
                    with urllib.request.urlopen(container["health_url"], timeout=3) as resp:
                        if 200 <= resp.status < 500:
                            healthy = True
                            break
                except Exception:
                    pass
            time.sleep(2)
            elapsed += 2

        if healthy:
            log(f"  {name} is healthy.")
        else:
            err(f"{name} health check timed out after {timeout}s")


# ── Service Lifecycle ──────────────────────────────────────────


def start_service(svc: dict) -> None:
    name = svc["name"]
    svc_type = svc["type"]
    port = svc["port"]
    cmd = svc["cmd"]
    health = svc["health"]
    workdir = svc["workdir"]

    pid = is_running(name)
    if pid is not None:
        log(f"{name} already running (PID {pid})")
        return

    log_dir = LOG_BASE / name
    log_dir.mkdir(parents=True, exist_ok=True)

    log(f"Starting {name} ({svc_type}) on :{port}")

    today = date.today().strftime("%Y-%m-%d")
    stdout_log = log_dir / f"{today}.log"
    stderr_log = log_dir / f"{today}.error.log"

    import shlex

    cmd_parts = shlex.split(cmd)

    with open(stdout_log, "ab") as fout, open(stderr_log, "ab") as ferr:
        proc = subprocess.Popen(
            cmd_parts,
            cwd=workdir,
            stdout=fout,
            stderr=ferr,
            start_new_session=True,
            env=_DAEMON_ENV,
        )

    pid = proc.pid
    (PID_DIR / f"{name}.pid").write_text(str(pid))

    timeout = 15 if svc_type == "binary" else 30
    if wait_for_health(health, timeout, name):
        log(f"  {name} started (PID {pid})")
    else:
        err(f"  {name} may not be healthy (PID {pid})")


def stop_service(svc: dict) -> None:
    name = svc["name"]
    pid = is_running(name)

    if pid is not None:
        log(f"Stopping {name} (PID {pid})")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        # Wait up to 10s for graceful shutdown
        waited = 0
        while waited < 10:
            try:
                os.kill(pid, 0)
                time.sleep(1)
                waited += 1
            except ProcessLookupError:
                break

        # Force kill if still running
        try:
            os.kill(pid, 0)
            log(f"  Force killing {name} (PID {pid})")
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        except ProcessLookupError:
            pass

        (PID_DIR / f"{name}.pid").unlink(missing_ok=True)
        log(f"  {name} stopped.")
    else:
        log(f"{name} is not running.")


def start_all() -> None:
    ensure_dirs()
    wait_for_docker()
    ensure_containers()
    for svc in SERVICES:
        start_service(svc)


def stop_all() -> None:
    for svc in reversed(SERVICES):
        stop_service(svc)
    log("All app services stopped. Docker containers left running.")


# ── Log Management ─────────────────────────────────────────────


def check_log_sizes() -> None:
    today = date.today().strftime("%Y-%m-%d")
    for service_dir in LOG_BASE.iterdir():
        if not service_dir.is_dir():
            continue
        for suffix in ["log", "error.log"]:
            logfile = service_dir / f"{today}.{suffix}"
            if not logfile.exists():
                continue
            size = logfile.stat().st_size
            if size > LOG_MAX_SIZE:
                if suffix == "error.log":
                    base = service_dir / f"{today}"
                    ext = "error.log"
                else:
                    base = service_dir / f"{today}"
                    ext = "log"

                n = 1
                while (service_dir / f"{today}.{n}.{ext}").exists() or (
                    service_dir / f"{today}.{n}.{ext}.gz"
                ).exists():
                    n += 1

                rotated = service_dir / f"{today}.{n}.{ext}"
                shutil.copy2(logfile, rotated)
                logfile.write_bytes(b"")  # Truncate, keep fd open
                log(f"Rotated {logfile} → {rotated} (was {size} bytes)")


def compress_old_logs() -> None:
    today = date.today().strftime("%Y-%m-%d")
    import re

    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}")

    for logfile in LOG_BASE.rglob("*.log"):
        filename = logfile.name
        if not date_pattern.match(filename):
            continue
        if filename.startswith(today):
            continue
        # Compress the file
        gz_path = logfile.with_suffix(logfile.suffix + ".gz")
        try:
            with open(logfile, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            logfile.unlink()
        except Exception:
            pass


def cleanup_old_logs() -> None:
    cutoff = time.time() - LOG_RETAIN_DAYS * 86400
    for gz_file in LOG_BASE.rglob("*.gz"):
        try:
            if gz_file.stat().st_mtime < cutoff:
                gz_file.unlink()
        except Exception:
            pass


# ── Health Check Loop ──────────────────────────────────────────


def health_check_all() -> None:
    for svc in SERVICES:
        name = svc["name"]
        if is_running(name) is None:
            log(f"ALERT: {name} is down — restarting...")
            start_service(svc)


# ── Daemon Mode ────────────────────────────────────────────────


def daemon_mode() -> None:
    log(f"Workshop Launcher daemon starting (PID {os.getpid()})")
    ensure_dirs()
    (PID_DIR / "launcher.pid").write_text(str(os.getpid()))

    start_all()

    last_rotate_date = ""
    shutdown_requested = False

    def handle_signal(signum, frame):
        nonlocal shutdown_requested
        log("Received signal, shutting down...")
        shutdown_requested = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while not shutdown_requested:
        time.sleep(60)
        if shutdown_requested:
            break
        health_check_all()
        check_log_sizes()
        today = date.today().strftime("%Y-%m-%d")
        if today != last_rotate_date:
            compress_old_logs()
            cleanup_old_logs()
            last_rotate_date = today

    stop_all()
    (PID_DIR / "launcher.pid").unlink(missing_ok=True)
    sys.exit(0)


# ── Status Display ─────────────────────────────────────────────


def cmd_status() -> None:
    print()
    print("Workshop Services Status")
    print("════════════════════════════════════════")

    # Docker containers
    print("[INFRA]")
    for container in DOCKER_CONTAINERS:
        name = container["name"]
        port = container["port"]

        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", name],
            capture_output=True,
            text=True,
        )
        state = result.stdout.strip() if result.returncode == 0 else "not found"

        health_result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}",
                name,
            ],
            capture_output=True,
            text=True,
        )
        health = health_result.stdout.strip() if health_result.returncode == 0 else ""

        if state == "running":
            if health == "healthy":
                status_str = "running (healthy)"
            else:
                status_str = "running"
            print(f"  {CHECKMARK} {name:<18} Docker    :{port:<6} {status_str}")
        else:
            print(f"  {CROSS} {name:<18} Docker    :{port:<6} {state}")

    # App services
    print()
    print("[APP]")
    for svc in SERVICES:
        name = svc["name"]
        svc_type = svc["type"]
        port = svc["port"]
        pid = is_running(name)
        if pid is not None:
            print(f"  {CHECKMARK} {name:<18} {svc_type:<9} :{port:<6} running (PID {pid})")
        else:
            print(f"  {CROSS} {name:<18} {svc_type:<9} :{port:<6} stopped")

    # Launcher daemon
    print()
    print("[LAUNCHER]")
    launcher_pidfile = PID_DIR / "launcher.pid"
    if launcher_pidfile.exists():
        try:
            lpid = int(launcher_pidfile.read_text().strip())
            os.kill(lpid, 0)
            print(f"  {CHECKMARK} daemon            {'':>25} running (PID {lpid})")
        except (ValueError, ProcessLookupError, PermissionError):
            try:
                lpid = int(launcher_pidfile.read_text().strip())
                print(f"  {CROSS} daemon            {'':>25} stale pidfile (PID {lpid})")
            except (ValueError, FileNotFoundError):
                print(f"  {CROSS} daemon            {'':>25} stale pidfile")
    else:
        print(f"  {CROSS} daemon            {'':>25} not running")

    # Log summary
    print()
    print(f"[LOGS]  {LOG_BASE}/")
    today = date.today().strftime("%Y-%m-%d")
    for svc in SERVICES:
        name = svc["name"]
        log_dir = LOG_BASE / name
        today_log = log_dir / f"{today}.log"
        if today_log.exists():
            size = today_log.stat().st_size
            if size >= 1048576:
                human_size = f"{size / 1048576:.1f}M"
            elif size >= 1024:
                human_size = f"{size / 1024:.1f}K"
            else:
                human_size = f"{size}B"
            print(f"  {name + '/':<16} {today}.log ({human_size})")
        else:
            print(f"  {name + '/':<16} (no logs today)")
    print()


# ── Logs Command ───────────────────────────────────────────────


def cmd_logs(args_rest: list[str]) -> int:
    import re

    if not args_rest:
        err("Usage: workshop_services.py logs <service> [date] [--error]")
        print("Available services:")
        for svc in SERVICES:
            print(f"  - {svc['name']}")
        return 1

    service = args_rest[0]
    remaining = args_rest[1:]

    log_dir = LOG_BASE / service
    if not log_dir.is_dir():
        err(f"No log directory for service: {service}")
        return 1

    error_flag = "--error" in remaining
    suffix = "error.log" if error_flag else "log"

    # Detect date argument (YYYY-MM-DD)
    target_date = None
    for arg in remaining:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", arg):
            target_date = arg
            break

    if target_date:
        # Historical log viewing
        target = log_dir / f"{target_date}.{suffix}"
        target_gz = Path(str(target) + ".gz")

        if target.exists():
            subprocess.run(["/usr/bin/less", str(target)])
        elif target_gz.exists():
            subprocess.run(["/usr/bin/zless", str(target_gz)])
        else:
            # Check for split files
            splits = sorted(log_dir.glob(f"{target_date}.*.{suffix}")) + sorted(
                log_dir.glob(f"{target_date}.*.{suffix}.gz")
            )
            if splits:
                print("Found split files:")
                for f in splits:
                    print(str(f))
                print("---")
                # Cat all to less
                data = b""
                for f in splits:
                    if str(f).endswith(".gz"):
                        with gzip.open(f, "rb") as gz:
                            data += gz.read()
                    else:
                        data += f.read_bytes()
                proc = subprocess.Popen(["/usr/bin/less"], stdin=subprocess.PIPE)
                proc.communicate(data)
            else:
                err(f"No log found: {target}")
                return 1
    else:
        # Live tail of today's log
        today = date.today().strftime("%Y-%m-%d")
        target = log_dir / f"{today}.{suffix}"
        if not target.exists():
            log(f"Log file not yet created: {target}")
            log("Waiting for first output...")
        try:
            subprocess.run(["/usr/bin/tail", "-f", str(target)])
        except Exception:
            err(f"Cannot tail {target} — file may not exist yet.")
            return 1

    return 0


# ── Manual Rotate ──────────────────────────────────────────────


def cmd_rotate() -> None:
    log("Running manual log rotation...")
    check_log_sizes()
    compress_old_logs()
    cleanup_old_logs()
    log("Done.")


# ── Main ───────────────────────────────────────────────────────


def find_service(name: str) -> dict | None:
    """Find a service by name."""
    for svc in SERVICES:
        if svc["name"] == name:
            return svc
    return None


def print_help(prog: str) -> None:
    print(f"Usage: {prog} {{daemon|start|stop|restart|status|rotate|logs}} [service]")
    print()
    print("Commands:")
    print("  daemon          Supervisor mode (used by LaunchAgent)")
    print("  start [name]    Start all services, or a single service by name")
    print("  stop [name]     Stop all app services, or a single service by name")
    print("  restart [name]  Stop + start (all or single)")
    print("  status          Show all service status")
    print("  rotate          Manual log rotation/compression")
    print("  logs <svc>            Tail today's stdout log")
    print("  logs <svc> --error    Tail today's stderr log")
    print("  logs <svc> <date>     View historical log (auto-decompress)")
    print("  logs <svc> <date> --error  View historical error log")
    print()
    svc_names = [s["name"] for s in SERVICES]
    print(f"Services: {', '.join(svc_names)}")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "--help", "-h"):
        print_help(sys.argv[0])
        sys.exit(0)

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "daemon":
        daemon_mode()
    elif cmd == "start":
        ensure_dirs()
        if rest:
            svc = find_service(rest[0])
            if not svc:
                err(f"Unknown service: {rest[0]}")
                sys.exit(1)
            start_service(svc)
        else:
            start_all()
    elif cmd == "stop":
        if rest:
            svc = find_service(rest[0])
            if not svc:
                err(f"Unknown service: {rest[0]}")
                sys.exit(1)
            stop_service(svc)
        else:
            stop_all()
    elif cmd == "restart":
        if rest:
            svc = find_service(rest[0])
            if not svc:
                err(f"Unknown service: {rest[0]}")
                sys.exit(1)
            stop_service(svc)
            time.sleep(2)
            ensure_dirs()
            start_service(svc)
        else:
            stop_all()
            time.sleep(2)
            ensure_dirs()
            start_all()
    elif cmd == "status":
        cmd_status()
    elif cmd == "rotate":
        cmd_rotate()
    elif cmd == "logs":
        sys.exit(cmd_logs(rest))
    else:
        err(f"Unknown command: {cmd}")
        print_help(sys.argv[0])
        sys.exit(1)


if __name__ == "__main__":
    main()
