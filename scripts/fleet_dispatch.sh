#!/usr/bin/env bash
# Fleet Dispatch — 一鍵派任務到 Windows Claude Code
# Usage: fleet-dispatch <issue_number> <prompt>
# Example: fleet-dispatch 17 "在 paper module 加全文搜尋功能"
set -e

ISSUE=${1:?用法: fleet-dispatch <issue_number> <prompt>}
PROMPT=${2:?缺少 prompt}
BRANCH="fleet/issue-${ISSUE}"
WORKSHOP="$HOME/workshop"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M")

echo "📋 Issue #${ISSUE} → Branch: ${BRANCH}"

# ── Step 1: Post dispatch notice to Issue ──
gh issue comment "$ISSUE" --body "$(cat <<GHEOF
## 🚀 Fleet Dispatch

| 項目 | 值 |
|------|-----|
| **Branch** | \`${BRANCH}\` |
| **Target** | win-gpu (WSL2 / RTX 3090) |
| **Mode** | code (headless) |
| **Time** | ${TIMESTAMP} |

### 任務指令

> ${PROMPT}

---
🤖 **Fleet Dispatcher** (mac-hub)
GHEOF
)" 2>/dev/null || true

# ── Step 2: Create branch + push ──
cd "$WORKSHOP"
git checkout -b "$BRANCH" 2>/dev/null || git checkout "$BRANCH"
git push -u origin "$BRANCH" 2>/dev/null || true
git checkout main

# ── Step 3: Bundle to Windows ──
git bundle create /tmp/fleet-dispatch.bundle "$BRANCH" ^main 2>/dev/null || true
cat /tmp/fleet-dispatch.bundle | ssh win-gpu "wsl -d Ubuntu -- bash -c 'cat > /tmp/fleet-dispatch.bundle'" 2>/dev/null || true

# ── Step 4: Checkout + Claude Code on Windows ──
echo "🚀 Dispatching to win-gpu..."
RESULT=$(ssh win-gpu "wsl -d Ubuntu -- bash -s" <<SSHEOF
export PATH="\$HOME/.local/bin:\$PATH"
cd ~/workshop

git fetch /tmp/fleet-dispatch.bundle "$BRANCH":"$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" 2>/dev/null || git checkout "$BRANCH"

claude -p "$PROMPT" --dangerously-skip-permissions 2>&1 | tail -30

git add -A
CHANGED=\$(git diff --cached --stat --no-color 2>/dev/null | tail -1)
git diff --cached --quiet || git commit -m "fleet/#${ISSUE}: \$(echo '$PROMPT' | head -c 50)"
echo "===FLEET_CHANGED===\$CHANGED"
SSHEOF
)

CHANGED_SUMMARY=$(echo "$RESULT" | grep "===FLEET_CHANGED===" | sed 's/===FLEET_CHANGED===//')
CLAUDE_OUTPUT=$(echo "$RESULT" | grep -v "===FLEET_CHANGED===")

# ── Step 5: Pull back results ──
echo "📥 Pulling results..."
ssh win-gpu "wsl -d Ubuntu -- bash -c 'cd ~/workshop && git bundle create /tmp/fleet-result.bundle HEAD ^main 2>/dev/null'"
ssh win-gpu "wsl -d Ubuntu -- bash -c 'cat /tmp/fleet-result.bundle'" > /tmp/fleet-result.bundle
git fetch /tmp/fleet-result.bundle "${BRANCH}:fleet/result-${ISSUE}" 2>/dev/null

# ── Step 6: Post completion to Issue ──
DIFF_STAT=$(git diff --stat main...fleet/result-${ISSUE} 2>/dev/null | tail -5)
FILES_CHANGED=$(git diff --name-only main...fleet/result-${ISSUE} 2>/dev/null | head -10)

gh issue comment "$ISSUE" --body "$(cat <<GHEOF
## ✅ Fleet 任務完成

### 變更摘要

\`\`\`
${DIFF_STAT}
\`\`\`

### 變更檔案

$(echo "$FILES_CHANGED" | while read f; do echo "- \`$f\`"; done)

### Claude Code 輸出（摘要）

\`\`\`
$(echo "$CLAUDE_OUTPUT" | tail -10)
\`\`\`

### 驗收指令

\`\`\`bash
git diff main...fleet/result-${ISSUE}                    # Review 改動
git merge fleet/result-${ISSUE} --no-ff                  # 滿意就 merge
gh issue close ${ISSUE}                                   # 關 Issue
\`\`\`

---
🎮 **Claude Code** (win-gpu / RTX 3090) · ${TIMESTAMP}
GHEOF
)" 2>/dev/null || true

echo ""
echo "📝 Review: git diff main...fleet/result-${ISSUE}"
echo "✅ Merge:  git merge fleet/result-${ISSUE} --no-ff && gh issue close ${ISSUE}"
