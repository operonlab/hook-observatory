#!/usr/bin/env bash
# switch-to-rust.sh — Final cutover: flip nginx + stop Python sentinel.
#
# This is the destructive Phase F step. Running this script will:
#   1. Verify Rust sentinel-rs on :4102 is healthy
#   2. Update /opt/homebrew/etc/nginx/conf.d/workshop-apps.inc
#      (sentinel location block 4101 → 4102)
#   3. Reload nginx
#   4. Stop Python sentinel via workshop_services.py
#
# Rollback with scripts/rollback-to-python.sh (writes to be added if needed).

set -uo pipefail

NGINX_CONF="/opt/homebrew/etc/nginx/conf.d/workshop-apps.inc"
WS_SERVICES="/Users/joneshong/workshop/scripts/workshop_services.py"
PYTHON="/Users/joneshong/.local/bin/python3"

log() { printf "\033[36m[cutover]\033[0m %s\n" "$*"; }
warn() { printf "\033[33m[warn]\033[0m %s\n" "$*"; }
err() { printf "\033[31m[err]\033[0m %s\n" "$*" >&2; }

# ── Step 0: pre-flight ──
log "Step 0: verifying Rust sentinel-rs on :4102"
code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:4102/api/sentinel/health)
if [[ "$code" != "200" ]]; then
    err "sentinel-rs /health returned $code — ABORT"
    exit 1
fi
log "  ✓ sentinel-rs healthy"

rss=$(ps -o rss= -p "$(pgrep -f 'target/release/sentinel-rs')" 2>/dev/null | awk '{print int($1/1024)}')
log "  ✓ RSS ${rss} MB"

# ── Step 1: back up nginx config ──
log "Step 1: backing up nginx config"
cp "$NGINX_CONF" "${NGINX_CONF}.before-sentinel-rs-$(date +%Y%m%d-%H%M%S)"
log "  ✓ backup created"

# ── Step 2: flip proxy_pass in the sentinel block ──
log "Step 2: flipping proxy_pass 4101 → 4102"
# Only change the occurrence inside the `# --- sentinel` block, not every 4101
/usr/bin/sed -i '' -E '/# --- sentinel/,/^}/ s|proxy_pass http://127\.0\.0\.1:4101|proxy_pass http://127.0.0.1:4102|g' "$NGINX_CONF"

# Sanity check: nginx -t
if ! /opt/homebrew/bin/nginx -t 2>&1; then
    err "nginx -t failed — restoring backup"
    cp "${NGINX_CONF}.before-sentinel-rs-"* "$NGINX_CONF" || true
    exit 1
fi
log "  ✓ nginx -t passed"

# ── Step 3: reload nginx ──
log "Step 3: nginx -s reload"
/opt/homebrew/bin/nginx -s reload
log "  ✓ nginx reloaded"

# Verify through nginx
sleep 1
code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/api/sentinel/health)
log "  nginx → sentinel health: HTTP $code"

# ── Step 4: stop Python sentinel ──
log "Step 4: stopping Python sentinel"
"$PYTHON" "$WS_SERVICES" stop sentinel
log "  ✓ Python sentinel stopped"

log ""
log "── Cutover complete ──"
log "Rust sentinel-rs is now serving /api/sentinel/*"
log "Python sentinel code retained at stations/sentinel/ for rollback."
