#!/usr/bin/env bash
# sync-from-workshop.sh — subtree split + push memvault core to downstream repo
#
# Usage (run from workshop root):
#   export MEMVAULT_OS_REMOTE=https://github.com/joneshong/memvault-os
#   ./docs/architecture/memvault-os-templates/scripts/sync-from-workshop.sh
#
# Or pass remote as first argument:
#   ./sync-from-workshop.sh https://github.com/joneshong/memvault-os
#
# Environment variables:
#   MEMVAULT_OS_REMOTE  — downstream repo remote URL (required if not passed as arg)
#   MEMVAULT_OS_BRANCH  — target branch in downstream repo (default: main)
#   WORKSHOP_ROOT       — path to workshop repo root (auto-detected via git rev-parse)
#   DRY_RUN             — set to "1" to print commands without executing
#
# What this script does:
#   1. Validate environment (git clean, remote reachable)
#   2. git subtree split --prefix=core/src/modules/memvault → temp branch
#   3. git push <remote> temp:main (--force if needed — downstream is append-only)
#   4. Clean up temp branch
#
# Security note: this script pushes to a remote repository. Ensure you have
# the correct remote URL before running — especially when using SSH remotes.

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SUBTREE_PREFIX="core/src/modules/memvault"
TEMP_BRANCH="memvault-os-sync-temp"
DOWNSTREAM_BRANCH="${MEMVAULT_OS_BRANCH:-main}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { echo "[sync-from-workshop] $*"; }
warn() { echo "[sync-from-workshop] WARNING: $*" >&2; }
die()  { echo "[sync-from-workshop] ERROR: $*" >&2; exit 1; }

run() {
    if [[ "${DRY_RUN:-0}" == "1" ]]; then
        echo "  [DRY_RUN] $*"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# Resolve workshop root
# ---------------------------------------------------------------------------

if [[ -n "${WORKSHOP_ROOT:-}" ]]; then
    cd "$WORKSHOP_ROOT"
else
    # Walk up from script location to find the git root
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    WORKSHOP_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
    cd "$WORKSHOP_ROOT"
fi
log "Workshop root: $WORKSHOP_ROOT"

# ---------------------------------------------------------------------------
# Resolve downstream remote
# ---------------------------------------------------------------------------

REMOTE_URL="${1:-${MEMVAULT_OS_REMOTE:-}}"
if [[ -z "$REMOTE_URL" ]]; then
    die "Downstream remote URL not set. Export MEMVAULT_OS_REMOTE or pass as first argument."
fi
log "Downstream remote: $REMOTE_URL"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

# Must be on main branch
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    die "Must run from 'main' branch, currently on '$CURRENT_BRANCH'."
fi

# Working tree must be clean (don't sync uncommitted changes)
if ! git diff --quiet HEAD; then
    die "Working tree has uncommitted changes. Commit or stash before syncing."
fi

# Subtree prefix must exist
if [[ ! -d "$SUBTREE_PREFIX" ]]; then
    die "Subtree prefix '$SUBTREE_PREFIX' does not exist in this repo."
fi

log "Pre-flight checks passed."

# ---------------------------------------------------------------------------
# Register temporary remote (if not already present)
# ---------------------------------------------------------------------------

REMOTE_NAME="memvault-os-sync-remote"

# Remove stale remote from previous run (ignore error if not present)
git remote remove "$REMOTE_NAME" 2>/dev/null || true

run git remote add "$REMOTE_NAME" "$REMOTE_URL"

# ---------------------------------------------------------------------------
# Cleanup handler — always remove temp branch + remote on exit
# ---------------------------------------------------------------------------

cleanup() {
    local exit_code=$?
    log "Cleaning up..."
    git branch -D "$TEMP_BRANCH" 2>/dev/null && log "  Deleted temp branch '$TEMP_BRANCH'" || true
    git remote remove "$REMOTE_NAME" 2>/dev/null && log "  Removed temp remote '$REMOTE_NAME'" || true
    if [[ $exit_code -ne 0 ]]; then
        warn "Sync failed (exit code $exit_code). Check errors above."
    fi
    exit $exit_code
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# subtree split
# ---------------------------------------------------------------------------

log "Splitting subtree '$SUBTREE_PREFIX' → branch '$TEMP_BRANCH' ..."

# If temp branch already exists from a previous failed run, remove it
git branch -D "$TEMP_BRANCH" 2>/dev/null || true

run git subtree split \
    --prefix="$SUBTREE_PREFIX" \
    --branch "$TEMP_BRANCH" \
    --squash

log "Subtree split complete."

# ---------------------------------------------------------------------------
# Push to downstream
# ---------------------------------------------------------------------------

log "Pushing '$TEMP_BRANCH' → $REMOTE_URL ($DOWNSTREAM_BRANCH) ..."

# --force: downstream 'main' is append-only managed by this script.
# The downstream repo should not have manual commits on main (adapter/ and
# deploy/ changes live on a separate 'templates' branch or are maintained
# by the downstream maintainer on a dedicated branch).
run git push --force "$REMOTE_NAME" "$TEMP_BRANCH:$DOWNSTREAM_BRANCH"

log "Push complete."

# ---------------------------------------------------------------------------
# Success — cleanup runs via trap
# ---------------------------------------------------------------------------

LAST_COMMIT="$(git log --oneline -1 "$TEMP_BRANCH" 2>/dev/null || echo '(dry run)')"
log "Sync successful."
log "  Synced commit: $LAST_COMMIT"
log "  Downstream: $REMOTE_URL → $DOWNSTREAM_BRANCH"
log ""
log "Next steps for downstream maintainer:"
log "  1. Merge upstream changes into working branch (adapter/ / deploy/ stay separate)"
log "  2. Verify tests pass in downstream CI"
log "  3. Tag a release if significant changes were included"
