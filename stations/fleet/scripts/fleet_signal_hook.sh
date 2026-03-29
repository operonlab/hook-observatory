#!/bin/bash
# Fleet completion signal — deployed to remote nodes.
# Triggered by tmux hook when Claude Code finishes a task.
# Sends HTTP POST back to Mac's fleet station via Tailscale.
#
# Required env vars (set by dispatcher before task dispatch):
#   FLEET_TASK_ID      — task UUID
#   FLEET_CALLBACK_URL — http://<mac-tailscale>:<port>/tasks/<id>/signal
#   FLEET_SECRET       — shared secret for authentication

set -euo pipefail

[ -z "${FLEET_TASK_ID:-}" ] && exit 0
[ -z "${FLEET_CALLBACK_URL:-}" ] && exit 0

curl -s -m 5 -X POST "$FLEET_CALLBACK_URL" \
  -H "x-fleet-secret: ${FLEET_SECRET:-}" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$FLEET_TASK_ID\", \"status\": \"completed\"}" \
  >/dev/null 2>&1 || true
