#!/usr/bin/env bash
# ws-memvault-synthesis.sh — Daily 4AM knowledge graph synthesis
#
# Pipeline (sequential, each step depends on the previous):
#   1. cluster_pipeline.py  — re-cluster all triples (GMM)
#   2. wisdom_pipeline.py   — synthesize cross-cluster wisdom (requires clusters)
#   3. confidence_decay_pipeline.py — decay stale attitude confidence (independent)
#   4. attitude_pipeline.py --all   — digest accumulated corrections
#   5. Tag sync + domain auto-promotion (threshold >= 10)
#   6. Reset triple counter (for threshold-based triggering)
#
# Logs: ~/workshop/outputs/memvault/logs/synthesis.log

set -u
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PIPELINES_DIR="$HOME/workshop/mcp/memvault/pipelines"
PYTHON="$HOME/.local/bin/python3"
LOG_DIR="$HOME/workshop/outputs/memvault/logs"
LOG_FILE="$LOG_DIR/synthesis.log"
CORRECTIONS_DIR="$HOME/workshop/outputs/memvault/corrections"
COUNTER_FILE="$HOME/.memvault-triple-counter"
CORE_API="http://localhost:8801/api/memvault"
DOMAIN_THRESHOLD=10

mkdir -p "$LOG_DIR"

log() {
  echo "[synthesis] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

log "========== Daily synthesis started =========="

# Step 1: Cluster pipeline (GMM re-clustering)
log "Step 1/6: cluster_pipeline.py"
if "$PYTHON" "$PIPELINES_DIR/cluster_pipeline.py" >> "$LOG_FILE" 2>&1; then
  log "Step 1 OK"
else
  log "Step 1 FAILED (exit $?) — continuing anyway"
fi

# Step 2: Wisdom pipeline (depends on fresh clusters)
log "Step 2/6: wisdom_pipeline.py"
if "$PYTHON" "$PIPELINES_DIR/wisdom_pipeline.py" >> "$LOG_FILE" 2>&1; then
  log "Step 2 OK"
else
  log "Step 2 FAILED (exit $?) — continuing anyway"
fi

# Step 3: Confidence decay (independent of clusters/wisdom)
log "Step 3/6: confidence_decay_pipeline.py"
if "$PYTHON" "$PIPELINES_DIR/confidence_decay_pipeline.py" >> "$LOG_FILE" 2>&1; then
  log "Step 3 OK"
else
  log "Step 3 FAILED (exit $?) — continuing anyway"
fi

# Step 4: Attitude pipeline — digest all accumulated corrections
log "Step 4/6: attitude_pipeline.py --all"
if [[ -d "$CORRECTIONS_DIR" ]]; then
  if "$PYTHON" "$PIPELINES_DIR/attitude_pipeline.py" --input "$CORRECTIONS_DIR" --all >> "$LOG_FILE" 2>&1; then
    log "Step 4 OK"
  else
    log "Step 4 FAILED (exit $?) — continuing anyway"
  fi
else
  log "Step 4 SKIP — no corrections directory"
fi

# Step 5: Tag sync + domain auto-promotion
log "Step 5/6: Tag sync + domain promotion"
SYNC_RESULT=$(curl -sf -X POST "${CORE_API}/tags/sync?space_id=default" 2>&1) && \
  log "  Tags synced: $SYNC_RESULT" || log "  Tag sync failed (API unreachable?)"

# Auto-promote tags with usage >= threshold to knowledge domains
PROMOTED=$("$PYTHON" -c "
import json, urllib.request
tags = json.loads(urllib.request.urlopen('${CORE_API}/tags?space_id=default').read())
domains = json.loads(urllib.request.urlopen('${CORE_API}/domains?space_id=default&page_size=200').read())
existing = {d['name'] for d in domains.get('items', [])}
new_tags = [t for t in tags if t['usage_count'] >= ${DOMAIN_THRESHOLD} and t['name'] not in existing]
promoted = 0
for t in new_tags:
    req = urllib.request.Request(
        '${CORE_API}/domains?space_id=default',
        data=json.dumps({'name': t['name'], 'description': f\"Auto-promoted (usage: {t['usage_count']})\"}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        resp = urllib.request.urlopen(req)
        if resp.status == 201: promoted += 1
    except: pass
print(promoted)
" 2>/dev/null)
log "  Domains promoted: ${PROMOTED:-0} new (threshold >= $DOMAIN_THRESHOLD)"
log "Step 5 OK"

# Step 6: Reset triple counter (for extract-triples.sh threshold trigger)
log "Step 6/6: Reset triple counter"
echo "0" > "$COUNTER_FILE"
log "Triple counter reset to 0"

log "========== Daily synthesis complete =========="
