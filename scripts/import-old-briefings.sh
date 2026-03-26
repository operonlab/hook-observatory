#!/usr/bin/env bash
# Import old daily briefing MD files into the new briefing module.
set -euo pipefail

BASE_URL="http://localhost:10000/api/briefing"
DOMAINS="ai finance geopolitics tech weather"
ANALYSTS="claude codex gemini"

created=0
entries=0
errors=0

# Collect date dirs, deduplicate
dates=""
for dir in ~/Claude/daily-briefing/2026-*/ ~/Claude/skills/daily-briefing/2026-*/; do
    [ -d "$dir" ] || continue
    d=$(basename "$dir")
    echo "$dates" | grep -q "$d" || dates="$dates $d:$dir"
done

for item in $(echo "$dates" | tr ' ' '\n' | sort); do
    [ -z "$item" ] && continue
    date="${item%%:*}"
    base="${item#*:}"
    raw_dir="${base}raw"

    if [ ! -d "$raw_dir" ]; then
        echo "SKIP $date: no raw/ dir"
        continue
    fi

    echo "--- $date ---"

    # Create domain briefings with raw entries
    for domain in $DOMAINS; do
        raw_file="${raw_dir}/${domain}.md"
        [ -f "$raw_file" ] || continue

        size=$(wc -c < "$raw_file" | tr -d ' ')
        if [ "$size" -lt 100 ]; then
            echo "  SKIP $domain: raw too small ($size bytes)"
            continue
        fi

        briefing_id=$(curl -s -X POST "${BASE_URL}/daily?space_id=default" \
            -H "Content-Type: application/json" \
            -d "$(jq -n --arg date "$date" --arg domain "$domain" \
                '{date: $date, domain: $domain, status: "completed"}')" \
            | jq -r '.id // empty')

        if [ -z "$briefing_id" ]; then
            echo "  ERROR $domain: failed to create briefing"
            errors=$((errors + 1))
            continue
        fi
        created=$((created + 1))

        content=$(cat "$raw_file")
        entry_id=$(curl -s -X POST "${BASE_URL}/daily/${briefing_id}/entries?space_id=default" \
            -H "Content-Type: application/json" \
            -d "$(jq -n --arg phase "raw" --arg key "$domain" --arg content "$content" \
                '{phase: $phase, key: $key, content: $content, metadata: {source: "imported"}}')" \
            | jq -r '.id // empty')
        [ -n "$entry_id" ] && entries=$((entries + 1)) || errors=$((errors + 1))
        echo "  $domain: briefing=$briefing_id"
    done

    # Create digest briefing for analysis + debate
    has_content=false
    for analyst in $ANALYSTS; do
        [ -f "${base}analysis/${analyst}.md" ] && has_content=true && break
        [ -f "${base}debate/${analyst}.md" ] && has_content=true && break
    done

    if $has_content; then
        digest_id=$(curl -s -X POST "${BASE_URL}/daily?space_id=default" \
            -H "Content-Type: application/json" \
            -d "$(jq -n --arg date "$date" \
                '{date: $date, domain: "digest", status: "completed"}')" \
            | jq -r '.id // empty')

        if [ -z "$digest_id" ]; then
            echo "  ERROR digest: failed to create"
            errors=$((errors + 1))
            continue
        fi
        created=$((created + 1))
        echo "  digest: briefing=$digest_id"

        for phase in analysis debate; do
            for analyst in $ANALYSTS; do
                fpath="${base}${phase}/${analyst}.md"
                [ -f "$fpath" ] || continue
                size=$(wc -c < "$fpath" | tr -d ' ')
                [ "$size" -lt 50 ] && continue

                content=$(cat "$fpath")
                entry_id=$(curl -s -X POST "${BASE_URL}/daily/${digest_id}/entries?space_id=default" \
                    -H "Content-Type: application/json" \
                    -d "$(jq -n --arg phase "$phase" --arg key "$analyst" --arg content "$content" \
                        '{phase: $phase, key: $key, content: $content, metadata: {source: "imported"}}')" \
                    | jq -r '.id // empty')
                [ -n "$entry_id" ] && entries=$((entries + 1)) || errors=$((errors + 1))
                echo "    ${phase}/${analyst}: OK"
            done
        done
    fi
done

echo ""
echo "=== Import Summary ==="
echo "Briefings created: $created"
echo "Entries created: $entries"
echo "Errors: $errors"
