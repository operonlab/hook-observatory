#!/bin/bash
# tmux_status.sh — Lightweight tmux status bar data provider.
# Replaces tmux_status.py to avoid 13× Python interpreter startup overhead.
#
# Usage: tmux_status.sh <metric>
# Metrics: cpu, mem, net, disk, cc, pressure,
#          cc-5h, cc-7d, cc-ex, cx-5h, cx-7d, gm-pro, gm-flash,
#          ex-segment

set -euo pipefail

JSON="/tmp/agent-metrics-sysmon.json"
METRIC="${1:-cpu}"
API_BASE="http://127.0.0.1:8795"

# Metric → JSON field mapping
field_for() {
    case "$1" in
        cpu)      echo "cpu_display" ;;
        mem)      echo "mem_display" ;;
        net)      echo "net_display" ;;
        disk)     echo "disk_display" ;;
        cc)       echo "cc_display" ;;
        pressure) echo "mem_pressure" ;;
        cc-5h)    echo "llm_cc_5h" ;;
        cc-7d)    echo "llm_cc_7d" ;;
        cc-ex)    echo "llm_cc_ex" ;;
        cx-5h)    echo "llm_cx_5h" ;;
        cx-7d)    echo "llm_cx_7d" ;;
        gm-pro)   echo "llm_gm_pro" ;;
        gm-flash) echo "llm_gm_flash" ;;
        *)        return 1 ;;
    esac
}

is_quota_metric() {
    case "$1" in
        cc-5h|cc-7d|cc-ex|cx-5h|cx-7d|gm-pro|gm-flash) return 0 ;;
        *) return 1 ;;
    esac
}

# Read from JSON file with staleness check
read_from_file() {
    local field="$1" max_age="$2"
    [[ -f "$JSON" ]] || return 1

    local now file_mtime age
    now=$(date +%s)
    file_mtime=$(stat -f %m "$JSON" 2>/dev/null) || return 1
    age=$(( now - file_mtime ))
    (( age > max_age )) && return 1

    local val
    val=$(jq -r --arg f "$field" '.[$f] // empty' "$JSON" 2>/dev/null) || return 1
    [[ -n "$val" && "$val" != "None" && "$val" != "null" ]] || return 1
    printf '%s' "$val"
}

# Read from API (fallback)
read_from_api() {
    local metric="$1" field="$2" url key
    if is_quota_metric "$metric"; then
        url="$API_BASE/quota/formatted"
        key="$metric"
    else
        url="$API_BASE/sysmon/current"
        key="$field"
    fi
    local val
    val=$(curl -sf --max-time 1 "$url" 2>/dev/null | jq -r --arg k "$key" '.[$k] // empty' 2>/dev/null) || return 1
    [[ -n "$val" && "$val" != "None" && "$val" != "null" ]] || return 1
    printf '%s' "$val"
}

# EX segment with Catppuccin styling
ex_segment() {
    local val
    val=$(get_metric "cc-ex") || true
    [[ -z "$val" || "$val" == "?" || "$val" == "off" ]] && return 0

    # Parse balance — hide if 余$0.00
    local balance
    balance=$(printf '%s' "$val" | grep -oE '余\$[0-9.]+' | grep -oE '[0-9.]+$') || true
    if [[ -n "$balance" ]]; then
        # Compare as integer cents to avoid bc dependency
        local cents
        cents=$(printf '%s' "$balance" | awk '{printf "%d", $1 * 100}')
        (( cents <= 0 )) && return 0
    fi

    local flamingo crust fg s0 mantle
    flamingo=$(tmux show -gqv @thm_flamingo 2>/dev/null)
    crust=$(tmux show -gqv @thm_crust 2>/dev/null)
    fg=$(tmux show -gqv @thm_fg 2>/dev/null)
    s0=$(tmux show -gqv @thm_surface_0 2>/dev/null)
    mantle=$(tmux show -gqv @thm_mantle 2>/dev/null)

    printf '#[fg=%s,bg=%s]#[fg=%s,bg=%s] EX #[fg=%s,bg=%s] %s #[fg=%s,bg=%s]' \
        "$flamingo" "$mantle" "$crust" "$flamingo" "$fg" "$s0" "$val" "$s0" "$mantle"
}

get_metric() {
    local metric="$1"
    local field max_age

    field=$(field_for "$metric") || { printf '?'; return; }

    if is_quota_metric "$metric"; then
        max_age=120
    else
        max_age=15
    fi

    read_from_file "$field" "$max_age" && return 0
    read_from_api "$metric" "$field" && return 0
    printf '?'
}

# Main
if [[ "$METRIC" == "ex-segment" ]]; then
    ex_segment
else
    get_metric "$METRIC"
fi
