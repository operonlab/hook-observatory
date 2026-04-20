#!/usr/bin/env bash
# orb-maintenance.sh — Graceful OrbStack VM reset
#
# Why: OrbStack Helper RSS grows over time (Linux page cache, Postgres WAL,
#      Qdrant/RustFS mmap). Restart is the only way to shrink it, but naive
#      restart risks colliding with scheduled DB writes.
#
# Prior incident: setting VM mem-limit broke session-archiver writes.
#   → Never auto-schedule this script. Run manually when notified.
#
# Safety:
#   1. Checks running Docker containers first
#   2. Graceful `docker compose stop` (SIGTERM → Postgres checkpoint + fsync)
#   3. `orb stop && orb start` (VM reset)
#   4. `docker compose up -d`
#   5. Health check before exit

set -uo pipefail  # NOT `set -e` — we need to handle each step explicitly

INFRA_DIR="$HOME/workshop/infra/docker"
KOMODO_DIR="$HOME/workshop/infra/komodo"

log() { printf "\033[36m[orb-maint]\033[0m %s\n" "$*"; }
warn() { printf "\033[33m[warn]\033[0m %s\n" "$*"; }
err() { printf "\033[31m[err]\033[0m %s\n" "$*" >&2; }

# ── Step 0: Pre-flight checks ──
log "Step 0: pre-flight checks"

if ! command -v orb >/dev/null 2>&1; then
    err "orb CLI not found. Install OrbStack first."
    exit 1
fi

if ! docker ps >/dev/null 2>&1; then
    err "Docker daemon not responding. OrbStack may already be down."
    exit 1
fi

RSS_BEFORE=$(ps -axm -o rss,comm | awk '/OrbStack Helper/ {sum+=$1} END {printf "%.2f", sum/1024/1024}')
log "Current OrbStack Helper RSS: ${RSS_BEFORE} GB"

echo
warn "This will briefly stop Workshop services (~30-60s total)."
warn "Before proceeding, verify NO critical jobs are running:"
warn "  • Cronicle dashboard: http://localhost:4105 (check 'Currently Running')"
warn "  • session-archiver, dailyos rituals, finance imports, etc."
echo
read -r -p "Continue? [y/N] " confirm
case "$confirm" in
    [yY]|[yY][eE][sS]) ;;
    *) log "Aborted."; exit 0 ;;
esac

# ── Step 1: Graceful container shutdown ──
log "Step 1: graceful docker compose stop (SIGTERM, 30s timeout)"

if [ -d "$KOMODO_DIR" ]; then
    (cd "$KOMODO_DIR" && docker compose stop --timeout 30) || warn "komodo stop partial"
fi

if [ -d "$INFRA_DIR" ]; then
    (cd "$INFRA_DIR" && docker compose stop --timeout 30) || warn "infra stop partial"
fi

# ── Step 2: OrbStack VM restart ──
log "Step 2: restarting OrbStack VM (page cache → zero)"
orb stop || warn "orb stop returned non-zero"
sleep 2
orb start
sleep 5

# ── Step 3: Bring containers back ──
log "Step 3: starting containers"

if [ -d "$INFRA_DIR" ]; then
    (cd "$INFRA_DIR" && docker compose up -d) || err "infra up failed"
fi

if [ -d "$KOMODO_DIR" ]; then
    (cd "$KOMODO_DIR" && docker compose up -d) || err "komodo up failed"
fi

# ── Step 4: Verify ──
log "Step 4: waiting 10s for health..."
sleep 10

log "Running containers:"
docker ps --format "  {{.Names}}\t{{.Status}}"

RSS_AFTER=$(ps -axm -o rss,comm | awk '/OrbStack Helper/ {sum+=$1} END {printf "%.2f", sum/1024/1024}')
log "OrbStack Helper RSS: ${RSS_BEFORE} GB → ${RSS_AFTER} GB"

# Reset notify cooldown so next alert fires promptly
rm -f "$HOME/.claude/data/system-monitor/.orb_notify_cooldown" 2>/dev/null || true

log "Done. Verify Postgres writes work:"
log "  curl -s http://localhost:10000/health | jq ."
