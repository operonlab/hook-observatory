#!/usr/bin/env bash
# verify_auto_survey_schedule.sh
# Validate Phase 4 outputs: plist syntax + manifest JSON + job presence

set -euo pipefail

WORKTREE="/Users/joneshong/workshop/.worktrees/feature/auto-survey-rs"
PLIST="$WORKTREE/infra/launchd/com.workshop.auto-survey-rs.plist"
MANIFEST="$WORKTREE/schedules/manifest.json"

PASS=0
FAIL=0

check() {
  local desc="$1"
  shift
  if "$@" > /dev/null 2>&1; then
    echo "  PASS: $desc"
    ((PASS++)) || true
  else
    echo "  FAIL: $desc"
    ((FAIL++)) || true
  fi
}

echo "=== Phase 4 Verification ==="

# 1. plist XML syntax
echo ""
echo "[1] launchd plist syntax"
check "plutil -lint plist" plutil -lint "$PLIST"
check "plist has Label=com.workshop.auto-survey-rs" \
  grep -q "com.workshop.auto-survey-rs" "$PLIST"
check "plist RunAtLoad=false" \
  grep -q "<false/>" "$PLIST"
check "plist KeepAlive=false" \
  grep -qc "<false/>" "$PLIST"
check "plist binary path exists (worktree)" \
  grep -q "auto-survey-rs/target/release/auto-survey-rs" "$PLIST"

# 2. manifest JSON validity
echo ""
echo "[2] manifest.json validity"
check "jq parse manifest" jq empty "$MANIFEST"
check "ws-auto-survey-rs-start-wed exists" \
  jq -e '.jobs[] | select(.name == "ws-auto-survey-rs-start-wed")' "$MANIFEST"
check "ws-auto-survey-rs-start-fri exists" \
  jq -e '.jobs[] | select(.name == "ws-auto-survey-rs-start-fri")' "$MANIFEST"
check "ws-auto-survey-rs-stop-wed exists" \
  jq -e '.jobs[] | select(.name == "ws-auto-survey-rs-stop-wed")' "$MANIFEST"
check "ws-auto-survey-rs-stop-fri exists" \
  jq -e '.jobs[] | select(.name == "ws-auto-survey-rs-stop-fri")' "$MANIFEST"
check "start-wed at Hour=10" \
  jq -e '.jobs[] | select(.name == "ws-auto-survey-rs-start-wed") | .schedule.calendar.Hour == 10' "$MANIFEST"
check "stop-wed at Hour=18" \
  jq -e '.jobs[] | select(.name == "ws-auto-survey-rs-stop-wed") | .schedule.calendar.Hour == 18' "$MANIFEST"

# 3. workshop_services.py
echo ""
echo "[3] workshop_services.py"
SERVICES_PY="$WORKTREE/scripts/workshop_services.py"
check "auto-survey-rs entry exists" \
  grep -q '"auto-survey-rs"' "$SERVICES_PY"
check "schedule=on-demand marker" \
  grep -q '"on-demand"' "$SERVICES_PY"

# 4. sentinel checker.py
echo ""
echo "[4] sentinel checker.py"
CHECKER_PY="$WORKTREE/stations/sentinel/checker.py"
check "auto-survey-rs light check exists" \
  grep -q '"auto-survey-rs"' "$CHECKER_PY"
check "auto-survey-rs is optional=True" \
  grep -A5 '"auto-survey-rs"' "$CHECKER_PY" | grep -q "optional=True"

# 5. Summary
echo ""
echo "==========================="
echo "PASS: $PASS  FAIL: $FAIL"
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: PASS"
else
  echo "RESULT: FAIL"
  exit 1
fi
