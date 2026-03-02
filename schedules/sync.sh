#!/usr/bin/env bash
# sync.sh — Synchronize workshop schedules manifest to launchd via scheduler skill
#
# Reads schedules/manifest.json, diffs against scheduler registry,
# and adds/removes jobs to keep them in sync.
#
# Usage:
#   bash ~/workshop/schedules/sync.sh              # sync
#   bash ~/workshop/schedules/sync.sh --dry-run    # preview changes
#   bash ~/workshop/schedules/sync.sh --force      # remove all ws- jobs, re-add from manifest

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFEST="$SCRIPT_DIR/manifest.json"
SCHEDULER="$SCRIPT_DIR/scheduler.py"
PYTHON="$HOME/.local/bin/python3"
REGISTRY="$HOME/workshop/outputs/scheduler/registry.json"

DRY_RUN=false
FORCE=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --force)   FORCE=true ;;
  esac
done

# Validate dependencies
if [[ ! -f "$MANIFEST" ]]; then
  echo "[error] Manifest not found: $MANIFEST" >&2
  exit 1
fi

if [[ ! -f "$SCHEDULER" ]]; then
  echo "[error] Scheduler script not found: $SCHEDULER" >&2
  exit 1
fi

JQ="$(command -v jq)"
if [[ -z "$JQ" ]]; then
  echo "[error] jq not found — install via: brew install jq" >&2
  exit 1
fi

echo "Workshop Schedule Sync"
echo "  Manifest : $MANIFEST"
echo "  Registry : $REGISTRY"
echo "  Mode     : $(${DRY_RUN} && echo 'DRY RUN' || echo 'LIVE')$(${FORCE} && echo ' + FORCE' || echo '')"
echo ""

# v2 schema: no prefix restriction — manifest is the single source of truth
# Read all manifest job names (labels used for matching)
MANIFEST_NAMES=()
MANIFEST_LABELS=()
while IFS=$'\t' read -r name label; do
  [[ -n "$name" ]] && MANIFEST_NAMES+=("$name")
  [[ -n "$label" ]] && MANIFEST_LABELS+=("$label")
done < <("$JQ" -r '.jobs[] | select(.enabled == true) | [.name, (.label // "")] | @tsv' "$MANIFEST")

# Read all jobs from registry (no longer filtered by prefix)
REGISTRY_NAMES=()
if [[ -f "$REGISTRY" ]]; then
  while IFS= read -r name; do
    [[ -n "$name" ]] && REGISTRY_NAMES+=("$name")
  done < <("$JQ" -r '.[].name' "$REGISTRY")
fi

echo "  Manifest jobs (enabled): ${MANIFEST_NAMES[*]:-none}"
echo "  Registry jobs          : ${REGISTRY_NAMES[*]:-none}"
echo ""

# Helper: check if value exists in a space-separated list
contains() {
  local needle="$1"; shift
  local item
  for item in "$@"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

# Calculate diff
TO_ADD=()
TO_REMOVE=()

# Jobs in manifest but not in registry → add
if [[ ${#MANIFEST_NAMES[@]} -gt 0 ]]; then
  for name in "${MANIFEST_NAMES[@]}"; do
    if [[ ${#REGISTRY_NAMES[@]} -eq 0 ]] || ! contains "$name" "${REGISTRY_NAMES[@]}" || $FORCE; then
      TO_ADD+=("$name")
    fi
  done
fi

# Jobs in registry but not in manifest → remove
if [[ ${#REGISTRY_NAMES[@]} -gt 0 ]]; then
  for name in "${REGISTRY_NAMES[@]}"; do
    if [[ ${#MANIFEST_NAMES[@]} -eq 0 ]] || ! contains "$name" "${MANIFEST_NAMES[@]}" || $FORCE; then
      TO_REMOVE+=("$name")
    fi
  done
fi

if [[ ${#TO_ADD[@]} -eq 0 ]] && [[ ${#TO_REMOVE[@]} -eq 0 ]]; then
  echo "[OK] Already in sync — no changes needed."
  exit 0
fi

echo "Changes:"
for name in "${TO_REMOVE[@]+"${TO_REMOVE[@]}"}"; do
  echo "  - REMOVE: $name"
done
for name in "${TO_ADD[@]+"${TO_ADD[@]}"}"; do
  echo "  + ADD:    $name"
done
echo ""

if $DRY_RUN; then
  echo "[dry-run] No changes applied."
  exit 0
fi

# Apply removals first
for name in "${TO_REMOVE[@]+"${TO_REMOVE[@]}"}"; do
  echo "[remove] $name"
  "$PYTHON" "$SCHEDULER" remove "$name" || true
done

# Apply additions
for name in "${TO_ADD[@]+"${TO_ADD[@]}"}"; do
  COMMAND="$("$JQ" -r --arg n "$name" '.jobs[] | select(.name == $n) | .command' "$MANIFEST")"
  SCHEDULE="$("$JQ" -c --arg n "$name" '.jobs[] | select(.name == $n) | .schedule' "$MANIFEST")"
  DESCRIPTION="$("$JQ" -r --arg n "$name" '.jobs[] | select(.name == $n) | .description // ""' "$MANIFEST")"

  echo "[add] $name → $COMMAND"
  "$PYTHON" "$SCHEDULER" add "$name" "$COMMAND" "$SCHEDULE" "$DESCRIPTION"
done

echo ""
echo "[OK] Sync complete."
