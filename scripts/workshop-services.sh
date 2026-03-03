#!/usr/bin/env bash
set -euo pipefail

# ════════════════════════════════════════════════════════════════
# Workshop Unified Service Launcher
# Single entry point for all workshop daemon services.
# ════════════════════════════════════════════════════════════════

LOG_BASE="/opt/homebrew/var/log/workshop"
PID_DIR="/opt/homebrew/var/run/workshop"
LOG_RETAIN_DAYS=90
LOG_MAX_SIZE=$((10 * 1024 * 1024))  # 10MB

# Service registry: name|type|start_command|port|health_check|working_dir
SERVICES=(
  # ── V2 Core ──
  "core|uvicorn|/Users/joneshong/workshop/.venv/bin/python3 -m uvicorn src.main:app --host 127.0.0.1 --port 8801 --env-file .env|8801|http://127.0.0.1:8801/docs|/Users/joneshong/workshop/core"
  # ── V1 Gateway (proxies V1 micro-services, will be removed after V2 migration) ──
  "gateway|uvicorn|/Users/joneshong/Claude/shared/.venv/bin/uvicorn gateway.main:app --host 127.0.0.1 --port 8800 --app-dir /Users/joneshong/Claude/services/gateway/src|8800|http://127.0.0.1:8800|/Users/joneshong/Claude/services/gateway"
  # ── Stations ──
  "agent-vista|binary|/Users/joneshong/workshop/stations/agent-vista/bin/agent-vista --no-browser --port 8840|8840|http://127.0.0.1:8840|/Users/joneshong/workshop/stations/agent-vista"
  "hook-observatory|uvicorn|/Users/joneshong/workshop/stations/hook-observatory/.venv/bin/python3 main.py|4100|http://127.0.0.1:4100|/Users/joneshong/workshop/stations/hook-observatory"
  "system-monitor|uvicorn|/Users/joneshong/workshop/stations/system-monitor/.venv/bin/python3 api.py --port 9526|9526|http://127.0.0.1:9526|/Users/joneshong/workshop/stations/system-monitor"
  "agentops|uvicorn|/Users/joneshong/workshop/stations/agentops/.venv/bin/python3 -m agentops serve|8795|http://127.0.0.1:8795/health|/Users/joneshong/workshop/stations/agentops"
  # sentinel 獨立於 workshop-services.sh — 由 launchd plist 管理（看門人不能被自己看守的人管）
  # ── Infrastructure Tools ──
  "litellm|binary|/Users/joneshong/.local/bin/litellm --config /Users/joneshong/.config/litellm/config.yaml --port 4000 --host 127.0.0.1|4000|http://127.0.0.1:4000|/Users/joneshong"
)

# Docker containers: name|port|health_command
# Health checks use docker exec (tools not installed on host)
DOCKER_CONTAINERS=(
  "ws-infra-postgres-1|5432|docker exec ws-infra-postgres-1 pg_isready"
  "ws-infra-redis-1|6379|docker exec ws-infra-redis-1 redis-cli ping"
  "ws-infra-rustfs-1|9000|curl -so /dev/null -w '%{http_code}' http://127.0.0.1:9000/ 2>/dev/null | grep -qE '^[2-4][0-9]{2}$'"
)

# ── Helpers ────────────────────────────────────────────────────

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
err() { log "ERROR: $*" >&2; }

ensure_dirs() {
    mkdir -p "$PID_DIR"
    for entry in "${SERVICES[@]}"; do
        local name="${entry%%|*}"
        mkdir -p "$LOG_BASE/$name"
    done
    mkdir -p "$LOG_BASE/launcher"
}

# Date-aware log writer: reads stdin line by line, appends to date-stamped file
date_logger() {
    local dir=$1 suffix=$2
    while IFS= read -r line; do
        echo "$line" >> "$dir/$(date +%Y-%m-%d).$suffix"
    done
}

parse_service() {
    local entry=$1
    IFS='|' read -r SVC_NAME SVC_TYPE SVC_CMD SVC_PORT SVC_HEALTH SVC_WORKDIR <<< "$entry"
}

is_running() {
    local pidfile="$PID_DIR/${1}.pid"
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
        rm -f "$pidfile"
    fi
    return 1
}

wait_for_health() {
    local url=$1 timeout=$2 name=$3
    local elapsed=0
    while [ "$elapsed" -lt "$timeout" ]; do
        if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    err "$name health check failed after ${timeout}s (url: $url)"
    return 1
}

# ── Docker ─────────────────────────────────────────────────────

wait_for_docker() {
    local timeout=120 elapsed=0
    log "Waiting for Docker Desktop..."
    while [ "$elapsed" -lt "$timeout" ]; do
        if docker info >/dev/null 2>&1; then
            log "Docker is ready."
            return 0
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
    err "Docker Desktop not ready after ${timeout}s"
    return 1
}

ensure_containers() {
    for entry in "${DOCKER_CONTAINERS[@]}"; do
        IFS='|' read -r name port health_cmd <<< "$entry"
        local state
        state=$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || echo "false")
        if [ "$state" != "true" ]; then
            log "Starting container: $name"
            docker start "$name" >/dev/null 2>&1 || { err "Failed to start $name"; continue; }
        fi
        log "Checking health: $name (:$port)"
        local timeout=30 elapsed=0
        while [ "$elapsed" -lt "$timeout" ]; do
            if eval "$health_cmd" >/dev/null 2>&1; then
                log "  $name is healthy."
                break
            fi
            sleep 2
            elapsed=$((elapsed + 2))
        done
        if [ "$elapsed" -ge "$timeout" ]; then
            err "$name health check timed out after ${timeout}s"
        fi
    done
}

# ── Service Lifecycle ──────────────────────────────────────────

start_service() {
    local entry=$1
    parse_service "$entry"

    if pid=$(is_running "$SVC_NAME"); then
        log "$SVC_NAME already running (PID $pid)"
        return 0
    fi

    local log_dir="$LOG_BASE/$SVC_NAME"
    mkdir -p "$log_dir"

    log "Starting $SVC_NAME ($SVC_TYPE) on :$SVC_PORT"
    cd "$SVC_WORKDIR"

    # Launch with date-aware log pipes
    $SVC_CMD \
        > >(date_logger "$log_dir" "log") \
        2> >(date_logger "$log_dir" "error.log") &
    local pid=$!
    echo "$pid" > "$PID_DIR/${SVC_NAME}.pid"

    # Health check
    local timeout=30
    [ "$SVC_TYPE" = "binary" ] && timeout=15
    if wait_for_health "$SVC_HEALTH" "$timeout" "$SVC_NAME"; then
        log "  $SVC_NAME started (PID $pid)"
    else
        err "  $SVC_NAME may not be healthy (PID $pid)"
    fi
}

stop_service() {
    local entry=$1
    parse_service "$entry"

    local pid
    if pid=$(is_running "$SVC_NAME"); then
        log "Stopping $SVC_NAME (PID $pid)"
        kill "$pid" 2>/dev/null || true
        # Wait up to 10s for graceful shutdown
        local waited=0
        while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt 10 ]; do
            sleep 1
            waited=$((waited + 1))
        done
        if kill -0 "$pid" 2>/dev/null; then
            log "  Force killing $SVC_NAME (PID $pid)"
            kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$PID_DIR/${SVC_NAME}.pid"
        log "  $SVC_NAME stopped."
    else
        log "$SVC_NAME is not running."
    fi
}

start_all() {
    ensure_dirs
    wait_for_docker
    ensure_containers
    for entry in "${SERVICES[@]}"; do
        start_service "$entry"
    done
}

stop_all() {
    # Reverse order
    local i
    for (( i=${#SERVICES[@]}-1; i>=0; i-- )); do
        stop_service "${SERVICES[$i]}"
    done
    # Docker containers are NOT stopped — managed by Docker Desktop
    log "All app services stopped. Docker containers left running."
}

# ── Log Management ─────────────────────────────────────────────

check_log_sizes() {
    local today
    today=$(date +%Y-%m-%d)
    for service_dir in "$LOG_BASE"/*/; do
        [ -d "$service_dir" ] || continue
        for logfile in "$service_dir"/${today}.log "$service_dir"/${today}.error.log; do
            [ -f "$logfile" ] || continue
            local size
            size=$(stat -f%z "$logfile" 2>/dev/null || echo 0)
            if [ "$size" -gt "$LOG_MAX_SIZE" ]; then
                local base ext n
                # Split: 2026-02-26.log → base=2026-02-26, ext=log (or error.log)
                local filename
                filename=$(basename "$logfile")
                if [[ "$filename" == *.error.log ]]; then
                    base="${service_dir}${filename%.error.log}"
                    ext="error.log"
                else
                    base="${service_dir}${filename%.log}"
                    ext="log"
                fi
                n=1
                while [ -f "${base}.${n}.${ext}" ] || [ -f "${base}.${n}.${ext}.gz" ]; do
                    ((n++))
                done
                cp "$logfile" "${base}.${n}.${ext}"
                : > "$logfile"  # truncate (fd stays open, service keeps writing)
                log "Rotated $logfile → ${base}.${n}.${ext} (was ${size} bytes)"
            fi
        done
    done
}

compress_old_logs() {
    local today
    today=$(date +%Y-%m-%d)
    # Only compress date-stamped logs (YYYY-MM-DD.*.log) that are NOT from today
    # This avoids compressing flat-named files like launcher.log
    find "$LOG_BASE" -regex '.*/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]\..*\.log' \
        -not -name "${today}*" -exec gzip -q {} \; 2>/dev/null || true
    # Also compress date-only logs (YYYY-MM-DD.log)
    find "$LOG_BASE" -regex '.*/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]\.log' \
        -not -name "${today}*" -exec gzip -q {} \; 2>/dev/null || true
}

cleanup_old_logs() {
    find "$LOG_BASE" -name "*.gz" -mtime +"${LOG_RETAIN_DAYS}" -delete 2>/dev/null || true
}

# ── Health Check Loop ──────────────────────────────────────────

health_check_all() {
    for entry in "${SERVICES[@]}"; do
        parse_service "$entry"
        if ! is_running "$SVC_NAME" >/dev/null; then
            log "ALERT: $SVC_NAME is down — restarting..."
            start_service "$entry"
        fi
    done
}

# ── Daemon Mode ────────────────────────────────────────────────

daemon_mode() {
    log "Workshop Launcher daemon starting (PID $$)"
    ensure_dirs
    echo $$ > "$PID_DIR/launcher.pid"

    start_all

    trap 'log "Received signal, shutting down..."; stop_all; rm -f "$PID_DIR/launcher.pid"; exit 0' SIGTERM SIGINT

    local last_rotate_date=""
    while true; do
        sleep 60
        health_check_all
        check_log_sizes
        local today
        today=$(date +%Y-%m-%d)
        if [ "$today" != "$last_rotate_date" ]; then
            compress_old_logs
            cleanup_old_logs
            last_rotate_date="$today"
        fi
    done
}

# ── Status Display ─────────────────────────────────────────────

cmd_status() {
    echo ""
    echo "Workshop Services Status"
    echo "════════════════════════════════════════"

    # Docker containers
    echo "[INFRA]"
    for entry in "${DOCKER_CONTAINERS[@]}"; do
        IFS='|' read -r name port health_cmd <<< "$entry"
        local state status_str
        state=$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null || echo "not found")
        local health
        health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$name" 2>/dev/null || echo "")
        if [ "$state" = "running" ]; then
            if [ "$health" = "healthy" ]; then
                status_str="running (healthy)"
            else
                status_str="running"
            fi
            printf "  ✓ %-18s Docker    :%-6s %s\n" "$name" "$port" "$status_str"
        else
            printf "  ✗ %-18s Docker    :%-6s %s\n" "$name" "$port" "$state"
        fi
    done

    # App services
    echo ""
    echo "[APP]"
    for entry in "${SERVICES[@]}"; do
        parse_service "$entry"
        local pid
        if pid=$(is_running "$SVC_NAME"); then
            printf "  ✓ %-18s %-9s :%-6s running (PID %s)\n" "$SVC_NAME" "$SVC_TYPE" "$SVC_PORT" "$pid"
        else
            printf "  ✗ %-18s %-9s :%-6s stopped\n" "$SVC_NAME" "$SVC_TYPE" "$SVC_PORT"
        fi
    done

    # Launcher daemon
    echo ""
    echo "[LAUNCHER]"
    if [ -f "$PID_DIR/launcher.pid" ]; then
        local lpid
        lpid=$(cat "$PID_DIR/launcher.pid")
        if kill -0 "$lpid" 2>/dev/null; then
            printf "  ✓ daemon            %25s running (PID %s)\n" "" "$lpid"
        else
            printf "  ✗ daemon            %25s stale pidfile (PID %s)\n" "" "$lpid"
        fi
    else
        printf "  ✗ daemon            %25s not running\n" ""
    fi

    # Log summary
    echo ""
    echo "[LOGS]  $LOG_BASE/"
    for entry in "${SERVICES[@]}"; do
        local name="${entry%%|*}"
        local log_dir="$LOG_BASE/$name"
        local today
        today=$(date +%Y-%m-%d)
        local today_log="$log_dir/${today}.log"
        if [ -f "$today_log" ]; then
            local size
            size=$(stat -f%z "$today_log" 2>/dev/null || echo 0)
            local human_size
            if [ "$size" -ge 1048576 ]; then
                human_size="$(echo "scale=1; $size / 1048576" | bc)M"
            elif [ "$size" -ge 1024 ]; then
                human_size="$(echo "scale=1; $size / 1024" | bc)K"
            else
                human_size="${size}B"
            fi
            printf "  %-16s %s.log (%s)\n" "$name/" "$today" "$human_size"
        else
            printf "  %-16s (no logs today)\n" "$name/"
        fi
    done
    echo ""
}

# ── Logs Command ───────────────────────────────────────────────

cmd_logs() {
    local service="${1:-}"
    local arg2="${2:-}"
    local arg3="${3:-}"

    if [ -z "$service" ]; then
        err "Usage: $0 logs <service> [date] [--error]"
        echo "Available services:"
        for entry in "${SERVICES[@]}"; do
            echo "  - ${entry%%|*}"
        done
        return 1
    fi

    local log_dir="$LOG_BASE/$service"
    if [ ! -d "$log_dir" ]; then
        err "No log directory for service: $service"
        return 1
    fi

    local suffix="log"

    # Detect --error flag
    [[ "$arg2" == "--error" || "$arg3" == "--error" ]] && suffix="error.log"

    # Detect date argument (YYYY-MM-DD)
    local target_date=""
    [[ "$arg2" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && target_date="$arg2"

    if [ -n "$target_date" ]; then
        # Historical log viewing
        local target="$log_dir/${target_date}.${suffix}"
        local target_gz="${target}.gz"

        if [ -f "$target" ]; then
            less "$target"
        elif [ -f "$target_gz" ]; then
            zless "$target_gz"
        else
            # Check for split files (copytruncate rotated)
            local splits
            splits=$(ls "$log_dir"/${target_date}.*."${suffix}" "$log_dir"/${target_date}.*."${suffix}".gz 2>/dev/null || true)
            if [ -n "$splits" ]; then
                echo "Found split files:"
                echo "$splits"
                echo "---"
                for f in $(echo "$splits" | sort); do
                    if [[ "$f" == *.gz ]]; then
                        zcat "$f"
                    else
                        cat "$f"
                    fi
                done | less
            else
                err "No log found: $target"
            fi
        fi
    else
        # Live tail of today's log
        local today
        today=$(date +%Y-%m-%d)
        local target="$log_dir/${today}.${suffix}"
        if [ ! -f "$target" ]; then
            log "Log file not yet created: $target"
            log "Waiting for first output..."
        fi
        tail -f "$target" 2>/dev/null || {
            err "Cannot tail $target — file may not exist yet."
            return 1
        }
    fi
}

# ── Manual Rotate ──────────────────────────────────────────────

cmd_rotate() {
    log "Running manual log rotation..."
    check_log_sizes
    compress_old_logs
    cleanup_old_logs
    log "Done."
}

# ── Main ───────────────────────────────────────────────────────

main() {
    local cmd="${1:-help}"
    shift || true

    case "$cmd" in
        daemon)   daemon_mode ;;
        start)    ensure_dirs; start_all ;;
        stop)     stop_all ;;
        restart)  stop_all; sleep 2; ensure_dirs; start_all ;;
        status)   cmd_status ;;
        rotate)   cmd_rotate ;;
        logs)     cmd_logs "$@" ;;
        help|--help|-h)
            echo "Usage: $0 {daemon|start|stop|restart|status|rotate|logs}"
            echo ""
            echo "Commands:"
            echo "  daemon          Supervisor mode (used by LaunchAgent)"
            echo "  start           Start all services (foreground, one-shot)"
            echo "  stop            Stop all app services (reverse order)"
            echo "  restart         Stop + start"
            echo "  status          Show all service status"
            echo "  rotate          Manual log rotation/compression"
            echo "  logs <svc>            Tail today's stdout log"
            echo "  logs <svc> --error    Tail today's stderr log"
            echo "  logs <svc> <date>     View historical log (auto-decompress)"
            echo "  logs <svc> <date> --error  View historical error log"
            ;;
        *)
            err "Unknown command: $cmd"
            main help
            exit 1
            ;;
    esac
}

main "$@"
