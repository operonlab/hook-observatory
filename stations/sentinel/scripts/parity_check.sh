#!/usr/bin/env bash
# parity_check.sh — compare Python sentinel (:4101) and Rust sentinel-rs (:4102)
#
# Usage: ./scripts/parity_check.sh
#
# Exits 0 if structural parity is confirmed, 1 otherwise.
# Structural parity = response shape + HTTP status, not literal value equality
# (values differ because each instance has its own tracker state).
#
# Requires: curl, jq

set -uo pipefail

PY_BASE="${PY_BASE:-http://127.0.0.1:4101}"
RS_BASE="${RS_BASE:-http://127.0.0.1:4102}"

FAIL=0
pass() { printf "  \033[32m✓\033[0m %s\n" "$*"; }
fail() { printf "  \033[31m✗\033[0m %s\n" "$*"; FAIL=$((FAIL+1)); }

echo "── Parity check: $PY_BASE  vs  $RS_BASE ──"
echo ""

# 1) /health: both public, both should 200 + have status field
check_health() {
    echo "[/api/sentinel/health]"
    local py rs py_status rs_status
    py=$(curl -sS "$PY_BASE/api/sentinel/health" 2>/dev/null || echo '')
    rs=$(curl -sS "$RS_BASE/api/sentinel/health" 2>/dev/null || echo '')
    py_status=$(jq -r '.status // "missing"' <<<"$py" 2>/dev/null)
    rs_status=$(jq -r '.status // "missing"' <<<"$rs" 2>/dev/null)
    [[ -n "$py" ]] && pass "Python /health responds" || fail "Python /health empty"
    [[ -n "$rs" ]] && pass "Rust /health responds" || fail "Rust /health empty"
    [[ "$py_status" == "healthy" || "$py_status" == "ok" ]] && pass "Python status=$py_status" || fail "Python status=$py_status unexpected"
    [[ "$rs_status" == "healthy" ]] && pass "Rust status=healthy" || fail "Rust status=$rs_status unexpected"
    echo ""
}

# 2) HTTP status for each endpoint (auth-gated endpoints may 401 — acceptable)
check_endpoints() {
    echo "[endpoint availability]"
    local endpoints=(
        "GET /api/sentinel/status"
        "GET /api/sentinel/status/core"
        "GET /api/sentinel/incidents"
        "GET /api/sentinel/uptime"
        "GET /api/sentinel/operations"
    )
    for ep in "${endpoints[@]}"; do
        local method="${ep%% *}"
        local path="${ep#* }"
        local py_code rs_code
        py_code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$PY_BASE$path")
        rs_code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$RS_BASE$path")
        # Acceptable outcomes: both 200, or Python 401 (auth) + Rust 200 (no auth yet)
        if [[ "$rs_code" == "200" && ("$py_code" == "200" || "$py_code" == "401") ]]; then
            pass "$ep  Python=$py_code Rust=$rs_code"
        else
            fail "$ep  Python=$py_code Rust=$rs_code (Rust expected 200)"
        fi
    done
    echo ""
}

# 3) Rust /status shape validation
check_rust_status_shape() {
    echo "[Rust /status shape]"
    local body overall total services
    body=$(curl -sS "$RS_BASE/api/sentinel/status")
    overall=$(jq -r '.overall // "missing"' <<<"$body")
    total=$(jq -r '.total // 0' <<<"$body")
    services=$(jq -r '.services | length' <<<"$body" 2>/dev/null || echo 0)
    [[ "$overall" != "missing" ]] && pass "has .overall ($overall)" || fail "missing .overall"
    [[ "$total" -gt 0 ]] && pass "total=$total" || fail "total=0"
    [[ "$services" -gt 0 ]] && pass "services[] length=$services" || fail "services[] empty"

    local sample_keys expected_keys
    sample_keys=$(jq -r '.services[0] | keys | sort | join(",")' <<<"$body" 2>/dev/null || echo "")
    expected_keys="first_failure_at,incident_id,last_light_check,light_status,response_ms,service,state"
    if [[ "$sample_keys" == "$expected_keys" ]]; then
        pass "service object keys match expected shape"
    else
        fail "shape mismatch: got=$sample_keys expected=$expected_keys"
    fi
    echo ""
}

# 4) Rust SQLite health_checks accumulating
check_db_growth() {
    echo "[Rust SQLite persistence]"
    local rows
    rows=$(sqlite3 /opt/homebrew/var/lib/workshop/sentinel.db "SELECT COUNT(*) FROM health_checks" 2>/dev/null || echo 0)
    [[ "$rows" -gt 0 ]] && pass "health_checks rows=$rows" || fail "health_checks empty"
    echo ""
}

check_health
check_endpoints
check_rust_status_shape
check_db_growth

if [[ "$FAIL" -eq 0 ]]; then
    echo "── All parity checks passed ──"
    exit 0
else
    echo "── $FAIL check(s) failed ──"
    exit 1
fi
