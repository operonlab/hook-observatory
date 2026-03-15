#!/usr/bin/env bash
# workshop-notify.sh — Send push notifications via Workshop notification system.
#
# Usage:
#   workshop-notify "標題" "內容"                        # via Redis → Core fan-out (Web Push + Bark)
#   workshop-notify "標題" "內容" --bark                  # direct Bark only (bypass Core)
#   workshop-notify "標題" "內容" --category sentinel     # set category
#   workshop-notify "標題" "內容" --severity critical     # set severity
#   workshop-notify "標題" "內容" --url /apps/sentinel/   # set click URL
#
# Environment:
#   BARK_SERVER_URL  — Bark server URL (default: http://localhost:8090)
#   BARK_DEVICE_KEY  — Bark device key (required for --bark mode)
#   REDIS_URL        — Redis URL (default: redis://localhost:6379/0)

set -euo pipefail

BARK_SERVER_URL="${BARK_SERVER_URL:-http://localhost:8090}"
BARK_DEVICE_KEY="${BARK_DEVICE_KEY:-}"

# Auto-detect redis-cli: local binary or Docker
if command -v redis-cli &>/dev/null; then
    REDIS_CMD="redis-cli"
elif docker ps --format '{{.Names}}' 2>/dev/null | grep -q redis; then
    REDIS_CONTAINER=$(docker ps --format '{{.Names}}' | grep redis | head -1)
    REDIS_CMD="docker exec $REDIS_CONTAINER redis-cli"
else
    REDIS_CMD=""
fi

# Defaults
CATEGORY="system"
SEVERITY="info"
URL="/"
TAG=""
MODE="redis"  # redis | bark

title=""
body=""

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --bark)       MODE="bark"; shift ;;
        --category)   CATEGORY="$2"; shift 2 ;;
        --severity)   SEVERITY="$2"; shift 2 ;;
        --url)        URL="$2"; shift 2 ;;
        --tag)        TAG="$2"; shift 2 ;;
        --help|-h)
            sed -n '2,12p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            if [[ -z "$title" ]]; then
                title="$1"
            elif [[ -z "$body" ]]; then
                body="$1"
            fi
            shift
            ;;
    esac
done

if [[ -z "$title" ]]; then
    echo "Error: title is required" >&2
    echo "Usage: workshop-notify \"title\" [\"body\"] [--bark] [--category X] [--severity X]" >&2
    exit 1
fi

if [[ "$MODE" == "bark" ]]; then
    # Direct Bark push (no Core dependency)
    if [[ -z "$BARK_DEVICE_KEY" ]]; then
        echo "Error: BARK_DEVICE_KEY not set" >&2
        exit 1
    fi

    encoded_title=$(python3 -c "from urllib.parse import quote; print(quote('$title'))")
    bark_url="${BARK_SERVER_URL}/${BARK_DEVICE_KEY}/${encoded_title}"

    if [[ -n "$body" ]]; then
        encoded_body=$(python3 -c "from urllib.parse import quote; print(quote('$body'))")
        bark_url="${bark_url}/${encoded_body}"
    fi

    params=""
    if [[ -n "$URL" && "$URL" != "/" ]]; then
        encoded_url=$(python3 -c "from urllib.parse import quote; print(quote('$URL', safe=''))")
        params="${params:+$params&}url=$encoded_url"
    fi
    if [[ -n "$CATEGORY" ]]; then
        encoded_cat=$(python3 -c "from urllib.parse import quote; print(quote('$CATEGORY', safe=''))")
        params="${params:+$params&}group=$encoded_cat"
    fi
    [[ "$SEVERITY" == "critical" || "$SEVERITY" == "warning" ]] && params="${params:+$params&}level=timeSensitive"
    [[ -n "$params" ]] && bark_url="${bark_url}?${params}"

    response=$(curl -s -o /dev/null -w "%{http_code}" "$bark_url")
    if [[ "$response" == "200" ]]; then
        echo "Bark notification sent: $title"
    else
        echo "Bark failed (HTTP $response)" >&2
        exit 1
    fi
else
    # Redis publish → Core notification fan-out (Web Push + Bark)
    payload=$(python3 -c "
import json
print(json.dumps({
    'category': '$CATEGORY',
    'title': '''$title''',
    'body': '''$body''',
    'url': '$URL',
    'tag': '$TAG' or None,
    'severity': '$SEVERITY',
    'user_id': None,
}, ensure_ascii=False))
")

    if [[ -z "$REDIS_CMD" ]]; then
        echo "Error: redis-cli not found (local or Docker)" >&2
        exit 1
    fi
    $REDIS_CMD PUBLISH workshop:push "$payload" > /dev/null 2>&1
    echo "Notification published: $title (via Redis → Core fan-out)"
fi
