#!/usr/bin/env bash
# ws-memvault-synthesis.sh — Daily 4AM knowledge graph synthesis
#
# Pipeline (sequential, each step depends on the previous):
#   1. cluster_pipeline.py  — re-cluster all triples (GMM)
#   2. wisdom_pipeline.py   — synthesize cross-cluster wisdom (requires clusters)
#   3. confidence_decay_pipeline.py — decay stale attitude confidence (independent)
#   4. attitude_pipeline.py --all   — digest accumulated corrections
#   5. Reset triple counter (for threshold-based triggering)
#
# Logs: ~/Claude/memvault/logs/synthesis.log

set -u
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PIPELINES_DIR="$HOME/workshop/mcp/memvault/pipelines"
PYTHON="$HOME/.local/bin/python3"
LOG_DIR="$HOME/Claude/memvault/logs"
LOG_FILE="$LOG_DIR/synthesis.log"
CORRECTIONS_DIR="$HOME/Claude/memvault/corrections"
COUNTER_FILE="$HOME/.memvault-triple-counter"

mkdir -p "$LOG_DIR"

log() {
  echo "[synthesis] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

log "========== Daily synthesis started =========="

# Step 1: Cluster pipeline (GMM re-clustering)
log "Step 1/5: cluster_pipeline.py"
if "$PYTHON" "$PIPELINES_DIR/cluster_pipeline.py" >> "$LOG_FILE" 2>&1; then
  log "Step 1 OK"
else
  log "Step 1 FAILED (exit $?) — continuing anyway"
fi

# Step 2: Wisdom pipeline (depends on fresh clusters)
log "Step 2/5: wisdom_pipeline.py"
if "$PYTHON" "$PIPELINES_DIR/wisdom_pipeline.py" >> "$LOG_FILE" 2>&1; then
  log "Step 2 OK"
else
  log "Step 2 FAILED (exit $?) — continuing anyway"
fi

# Step 3: Confidence decay (independent of clusters/wisdom)
log "Step 3/5: confidence_decay_pipeline.py"
if "$PYTHON" "$PIPELINES_DIR/confidence_decay_pipeline.py" >> "$LOG_FILE" 2>&1; then
  log "Step 3 OK"
else
  log "Step 3 FAILED (exit $?) — continuing anyway"
fi

# Step 4: Attitude pipeline — digest all accumulated corrections
log "Step 4/5: attitude_pipeline.py --all"
if [[ -d "$CORRECTIONS_DIR" ]]; then
  if "$PYTHON" "$PIPELINES_DIR/attitude_pipeline.py" --input "$CORRECTIONS_DIR" --all >> "$LOG_FILE" 2>&1; then
    log "Step 4 OK"
  else
    log "Step 4 FAILED (exit $?) — continuing anyway"
  fi
else
  log "Step 4 SKIP — no corrections directory"
fi

# Step 5: Reset triple counter (for extract-triples.sh threshold trigger)
log "Step 5/5: Reset triple counter"
echo "0" > "$COUNTER_FILE"
log "Triple counter reset to 0"

log "========== Daily synthesis complete =========="
