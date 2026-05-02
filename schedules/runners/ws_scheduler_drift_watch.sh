#!/bin/bash
# ws_scheduler_drift_watch.sh — daily watchdog: detect plist drift and auto-reload.
#
# Why: macOS launchd does NOT auto-reload after plist edits. Silent drift
# means scheduled jobs run the OLD command. Symptom: 4/24 ws-auto-survey-fri
# kept invoking the deleted ws_auto_survey.py, exit 2, no LINE OCR, no URLs.
#
# Strategy: run before any time-sensitive scheduled job (auto-survey daemon
# starts at 10:00 on Wed/Fri, so we run at 09:00 daily).

set -u
trap 'echo "[drift-watch] exit ($?)"' EXIT

PY="$HOME/.local/bin/python3"
SCHEDULER="$HOME/workshop/schedules/scheduler.py"
BARK_URL="http://127.0.0.1:8090"

bark() {
  local title="$1" body="$2"
  local et eb
  et=$(printf '%s' "$title" | "$PY" -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.stdin.read()),end="")')
  eb=$(printf '%s' "$body"  | "$PY" -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.stdin.read()),end="")')
  curl -sS -m 3 "${BARK_URL}/${et}/${eb}?group=scheduler-drift&sound=silence" >/dev/null 2>&1 || true
}

ts() { date '+%F %T'; }

drift_json=$("$PY" "$SCHEDULER" drift-check 2>&1)
drift_count=$(printf '%s' "$drift_json" | "$PY" -c 'import json,sys;print(json.loads(sys.stdin.read()).get("count",0))' 2>/dev/null || echo 0)

if [[ "$drift_count" -eq 0 ]]; then
  echo "[$(ts)] no drift"
  exit 0
fi

names=$(printf '%s' "$drift_json" | "$PY" -c 'import json,sys;d=json.loads(sys.stdin.read());print(", ".join(r["label"].removeprefix("com.joneshong.scheduler.") for r in d["drift"]))' 2>/dev/null)
echo "[$(ts)] drift detected ($drift_count): $names"

reload_json=$("$PY" "$SCHEDULER" reload-all 2>&1)
echo "$reload_json"

bark "Scheduler drift fixed" "$drift_count job(s) reloaded: $names"
