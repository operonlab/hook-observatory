#!/usr/bin/env bash
# ws-envkit-snapshot.sh — Weekly environment snapshot + config backup + drift detection
#
# Pipeline (sequential):
#   1. envkit snapshot  — capture full environment state
#   2. envkit backup    — backup Tier 1-2 config files
#   3. envkit diff      — compare with previous snapshot (drift detection)
#   4. Rotate old snapshots (keep last 12)
#
# Logs: ~/workshop/outputs/scheduler/logs/ws-envkit-snapshot.log

set -u
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

ENVKIT_DIR="$HOME/workshop/stations/envkit"
PYTHON="$HOME/.local/bin/python3"
SNAPSHOT_DIR="$ENVKIT_DIR/snapshots"
CONFIGS_DIR="$ENVKIT_DIR/configs"
LOG_DIR="$HOME/workshop/outputs/scheduler/logs"
LOG_FILE="$LOG_DIR/ws-envkit-snapshot.log"
MAX_SNAPSHOTS=12

mkdir -p "$LOG_DIR" "$SNAPSHOT_DIR" "$CONFIGS_DIR"

log() {
  echo "[envkit] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

log "========== EnvKit snapshot started =========="

# Find the most recent previous snapshot for diff
PREV_SNAPSHOT=$(ls -1t "$SNAPSHOT_DIR"/mac-mini-*.yaml 2>/dev/null | head -1)
TODAY=$(date '+%Y-%m-%d')
CURRENT_SNAPSHOT="$SNAPSHOT_DIR/mac-mini-${TODAY}.yaml"

# Step 1: Take snapshot
log "Step 1/4: envkit snapshot"
if "$PYTHON" "$ENVKIT_DIR/envkit.py" snapshot --output "$CURRENT_SNAPSHOT" >> "$LOG_FILE" 2>&1; then
  log "Step 1 OK — saved to $CURRENT_SNAPSHOT"
else
  log "Step 1 FAILED (exit $?) — aborting"
  exit 1
fi

# Step 2: Backup configs
log "Step 2/4: envkit backup"
if "$PYTHON" "$ENVKIT_DIR/envkit.py" backup --output-dir "$CONFIGS_DIR" >> "$LOG_FILE" 2>&1; then
  log "Step 2 OK — configs backed up to $CONFIGS_DIR"
else
  log "Step 2 FAILED (exit $?) — continuing anyway"
fi

# Step 3: Diff with previous snapshot (drift detection)
log "Step 3/4: drift detection"
if [[ -n "$PREV_SNAPSHOT" && -f "$PREV_SNAPSHOT" && "$PREV_SNAPSHOT" != "$CURRENT_SNAPSHOT" ]]; then
  DIFF_OUTPUT=$("$PYTHON" "$ENVKIT_DIR/envkit.py" diff "$PREV_SNAPSHOT" "$CURRENT_SNAPSHOT" 2>&1)
  DIFF_EXIT=$?
  if [[ $DIFF_EXIT -eq 0 ]]; then
    if echo "$DIFF_OUTPUT" | grep -qi "no differences\|identical\|0 changes"; then
      log "  No drift detected since $(basename "$PREV_SNAPSHOT")"
    else
      log "  Drift detected since $(basename "$PREV_SNAPSHOT"):"
      echo "$DIFF_OUTPUT" | head -30 >> "$LOG_FILE"
      log "  (see log for details)"
    fi
  else
    log "  Diff command failed (exit $DIFF_EXIT)"
  fi
  log "Step 3 OK"
else
  log "Step 3 SKIP — no previous snapshot to compare"
fi

# Step 4: Rotate old snapshots (keep last N)
log "Step 4/4: rotate snapshots (keep last $MAX_SNAPSHOTS)"
SNAPSHOT_COUNT=$(ls -1 "$SNAPSHOT_DIR"/mac-mini-*.yaml 2>/dev/null | wc -l | tr -d ' ')
if [[ "$SNAPSHOT_COUNT" -gt "$MAX_SNAPSHOTS" ]]; then
  REMOVE_COUNT=$((SNAPSHOT_COUNT - MAX_SNAPSHOTS))
  ls -1t "$SNAPSHOT_DIR"/mac-mini-*.yaml | tail -"$REMOVE_COUNT" | while read -r old; do
    rm -f "$old"
    log "  Removed old snapshot: $(basename "$old")"
  done
  log "  Rotated: removed $REMOVE_COUNT old snapshots"
else
  log "  No rotation needed ($SNAPSHOT_COUNT/$MAX_SNAPSHOTS)"
fi

log "========== EnvKit snapshot complete =========="
