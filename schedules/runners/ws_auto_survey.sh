#!/usr/bin/env bash
# ws_auto_survey.sh — Wed/Fri 13:00 auto-survey orchestrator.
#
# Drives the auto-survey binary directly — no Python, no uv, no Postgres.
#
# Timeline:
#   13:00       Cronicle triggers this script
#   13:00~14:00 Phase 0: LINE poll every 10 min (screenshot + OCR via Rust)
#   14:00       Decision point — if URLs present → `run` pipeline (Bark summary)
#               otherwise enter Phase 1
#   14:00~15:00 Phase 1: Bark reminder every 10 min until URLs appear or timeout

set -u
trap 'echo "[ws_auto_survey] exiting ($?)"' EXIT

BIN="/Users/joneshong/.cargo/shared-target/release/auto-survey-rs"
DB="/Users/joneshong/workshop/stations/auto-survey/data/auto_survey.db"
export AUTO_SURVEY_SQLITE_PATH="$DB"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

EXECUTION_HOUR=14
LINE_POLL_INTERVAL=600     # 10 minutes
BARK_POLL_INTERVAL=600     # 10 minutes
MAX_DURATION=7200          # 2 hours (13:00 ~ 15:00)

log() { printf '[ws_auto_survey] %s\n' "$*"; }

# Return today's DailyRun state as KEY=VALUE on stdout.
# `IFS=: read -r key value` splits on the FIRST colon only, so URL values
# keep their 'https://' intact.
read_status() {
    "$BIN" today-status 2>/dev/null | while IFS=: read -r key value; do
        [[ -z "$key" ]] && continue
        printf '%s=%s\n' "$key" "$value"
    done
}

# Try one LINE read via Rust. Returns 0 if URLs were saved, 1 otherwise.
try_line_read() {
    log "LINE read (screenshot + OCR via Rust)..."
    "$BIN" line-read || return 1
    return 0
}

trigger_pipeline() {
    local attend="$1" quiz="$2"
    local args=(run)
    [[ -n "$attend" ]] && args+=(--attend-url "$attend")
    [[ -n "$quiz"   ]] && args+=(--quiz-url   "$quiz")
    log "Triggering pipeline: ${args[*]}"
    "$BIN" "${args[@]}"
}

START=$(date +%s)
now_hour() { date +%H | sed 's/^0//'; }
elapsed() { echo $(( $(date +%s) - START )); }

# ── Phase 0: LINE poll (13:00 ~ 14:00) ──
log "Phase 0: LINE poll started"
while [[ $(now_hour) -lt $EXECUTION_HOUR ]]; do
    if (( $(elapsed) > MAX_DURATION )); then
        break
    fi
    if try_line_read; then
        log "Phase 0: URLs found, waiting for execution hour"
        break
    fi
    log "No URLs yet, retry in ${LINE_POLL_INTERVAL}s"
    sleep "$LINE_POLL_INTERVAL"
done

# ── Wait until execution hour ──
CUR=$(now_hour)
if [[ $CUR -lt $EXECUTION_HOUR ]]; then
    TARGET_EPOCH=$(date -v"${EXECUTION_HOUR}H" -v0M -v0S +%s)
    NOW_EPOCH=$(date +%s)
    DELAY=$(( TARGET_EPOCH - NOW_EPOCH ))
    if (( DELAY > 0 )); then
        log "Waiting ${DELAY}s until ${EXECUTION_HOUR}:00"
        sleep "$DELAY"
    fi
fi

# ── Decision point at execution hour ──
log "${EXECUTION_HOUR}:00 decision point"
eval "$(read_status)"
: "${status:=none}"
: "${attend_url:=}"
: "${quiz_url:=}"

if [[ -n "$attend_url" || -n "$quiz_url" ]]; then
    trigger_pipeline "$attend_url" "$quiz_url"
    exit $?
fi

# ── Phase 1: Bark reminders ──
log "Phase 1: Bark reminders (every ${BARK_POLL_INTERVAL}s)"
while (( $(elapsed) < MAX_DURATION )); do
    "$BIN" notify-check
    sleep "$BARK_POLL_INTERVAL"

    eval "$(read_status)"
    : "${status:=none}"
    : "${attend_url:=}"
    : "${quiz_url:=}"

    case "$status" in
        running|completed)
            log "Pipeline handled externally (status=$status), exiting."
            exit 0
            ;;
    esac

    if [[ -n "$attend_url" || -n "$quiz_url" ]]; then
        log "URLs provided manually, triggering pipeline."
        trigger_pipeline "$attend_url" "$quiz_url"
        exit $?
    fi
done

log "Timeout reached, exiting."
exit 0
