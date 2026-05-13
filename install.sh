#!/usr/bin/env bash
# hook-dispatcher installer
#
# Registers the Go binary as Claude Code's hook executor by writing 10 event
# entries into ~/.claude/settings.json.
#
# Usage:
#   ./install.sh                       Build (if needed), deploy binary to
#                                      ~/.claude/hooks/, write settings.json
#   ./install.sh --uninstall           Remove the 10 hook entries from
#                                      settings.json (binary file is left in
#                                      place — `rm` it manually if you want)
#   ./install.sh --dry-run             Print what would change, touch nothing
#   ./install.sh --binary <path>       Use an existing binary instead of
#                                      building (for Homebrew formulae /
#                                      pre-built releases)
#
# Requires: bash 4+, jq. Build path additionally needs go and git.

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DISPATCHER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${HOME}/.claude"
HOOKS_DIR="${CLAUDE_DIR}/hooks"
SETTINGS_JSON="${CLAUDE_DIR}/settings.json"
DISPATCHER_TARGET="${HOOKS_DIR}/hook-dispatcher"
CONFIG_EXAMPLE="${DISPATCHER_ROOT}/config.example.yaml"
CONFIG_USER="${DISPATCHER_ROOT}/config.yaml"

# ---------------------------------------------------------------------------
# Hook events and their default timeouts (seconds). Using parallel arrays +
# case lookup instead of associative arrays so this works on macOS's stock
# bash 3.2. Runtime can override via config.yaml `hook_timeouts:` block —
# this script only seeds the initial settings.json.
# ---------------------------------------------------------------------------

EVENTS=(
  PreToolUse PostToolUse Stop Notification
  SessionStart SessionEnd SubagentStart SubagentStop
  UserPromptSubmit PreCompact
)

timeout_for() {
  case "$1" in
    PreToolUse)        echo 20  ;;
    PostToolUse)       echo 35  ;;
    Stop)              echo 20  ;;
    Notification)      echo 20  ;;
    SessionStart)      echo 35  ;;
    SessionEnd)        echo 20  ;;
    SubagentStart)     echo 10  ;;
    SubagentStop)      echo 120 ;;
    UserPromptSubmit)  echo 20  ;;
    PreCompact)        echo 10  ;;
    *) echo 20 ;;
  esac
}

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

mode="install"
dry_run=0
binary_override=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall) mode="uninstall"; shift ;;
    --dry-run)   dry_run=1; shift ;;
    --binary)    binary_override="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() { printf '%s\n' "$*" >&2; }
err() { printf 'ERROR: %s\n' "$*" >&2; }
maybe() {
  if [[ "$dry_run" -eq 1 ]]; then
    log "  (dry-run) $*"
  else
    eval "$@"
  fi
}

require_jq() {
  command -v jq >/dev/null 2>&1 || {
    err "jq is required (install: brew install jq)"
    exit 1
  }
}

# ---------------------------------------------------------------------------
# Build / locate binary
# ---------------------------------------------------------------------------

resolve_binary() {
  if [[ -n "$binary_override" ]]; then
    [[ -x "$binary_override" ]] || { err "binary not executable: $binary_override"; exit 1; }
    echo "$binary_override"
    return
  fi

  local local_bin="${DISPATCHER_ROOT}/bin/hook-dispatcher"
  if [[ -x "$local_bin" ]]; then
    echo "$local_bin"
    return
  fi

  # Need to build
  command -v go >/dev/null 2>&1 || {
    err "Go binary missing and 'go' not in PATH. Run 'make build' or pass --binary."
    exit 1
  }
  log "Building hook-dispatcher..."
  if [[ "$dry_run" -eq 0 ]]; then
    (cd "$DISPATCHER_ROOT" && make build >/dev/null)
  fi
  echo "$local_bin"
}

# ---------------------------------------------------------------------------
# settings.json manipulation
# ---------------------------------------------------------------------------

build_hooks_json() {
  # Emit a JSON object: { "<event>": [ { matcher, hooks: [{type, command, timeout}] } ] }
  local target="$1"
  local out="{"
  local first=1
  local evt timeout
  for evt in "${EVENTS[@]}"; do
    timeout=$(timeout_for "$evt")
    [[ "$first" -eq 1 ]] || out+=","
    first=0
    out+=$(printf '"%s":[{"matcher":"","hooks":[{"type":"command","command":"%s %s","timeout":%s}]}]' \
      "$evt" "$target" "$evt" "$timeout")
  done
  out+="}"
  echo "$out"
}

write_settings() {
  local target="$1"
  local hooks_json
  hooks_json=$(build_hooks_json "$target")

  mkdir -p "$(dirname "$SETTINGS_JSON")"
  if [[ ! -f "$SETTINGS_JSON" ]]; then
    log "  creating new $SETTINGS_JSON"
    if [[ "$dry_run" -eq 0 ]]; then
      jq -n --argjson h "$hooks_json" '{hooks: $h}' > "$SETTINGS_JSON"
    fi
    return
  fi

  # Merge into existing settings.json (replace .hooks)
  log "  updating $SETTINGS_JSON (.hooks replaced)"
  if [[ "$dry_run" -eq 0 ]]; then
    local tmp="${SETTINGS_JSON}.tmp.$$"
    jq --argjson h "$hooks_json" '.hooks = $h' "$SETTINGS_JSON" > "$tmp"
    mv "$tmp" "$SETTINGS_JSON"
  fi
}

remove_settings_hooks() {
  [[ -f "$SETTINGS_JSON" ]] || { log "  no $SETTINGS_JSON, nothing to remove"; return; }
  log "  removing .hooks from $SETTINGS_JSON"
  if [[ "$dry_run" -eq 0 ]]; then
    local tmp="${SETTINGS_JSON}.tmp.$$"
    jq 'del(.hooks)' "$SETTINGS_JSON" > "$tmp"
    mv "$tmp" "$SETTINGS_JSON"
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

require_jq

if [[ "$mode" == "uninstall" ]]; then
  log "hook-dispatcher uninstaller"
  log "============================"
  remove_settings_hooks
  log ""
  log "Done. The binary at $DISPATCHER_TARGET is left in place — remove it"
  log "manually if you no longer need it. Restart Claude Code to apply."
  exit 0
fi

log "hook-dispatcher installer"
log "=========================="

# 1. Resolve binary (build if needed, or use --binary)
log ""
log "[1/3] Locating binary..."
binary=$(resolve_binary)
log "  source: $binary"

# 2. Deploy binary
log ""
log "[2/3] Deploying → $DISPATCHER_TARGET"
maybe "mkdir -p '$HOOKS_DIR'"
maybe "cp '$binary' '$DISPATCHER_TARGET'"
maybe "chmod +x '$DISPATCHER_TARGET'"
log "  installed"

# 3. Register 10 hook events in settings.json
log ""
log "[3/3] Registering hooks → $SETTINGS_JSON"
write_settings "$DISPATCHER_TARGET"

# 4. Optionally seed config.yaml from example
if [[ ! -f "$CONFIG_USER" ]]; then
  log ""
  log "[bonus] Seeding $CONFIG_USER from config.example.yaml"
  if [[ -f "$CONFIG_EXAMPLE" ]]; then
    maybe "cp '$CONFIG_EXAMPLE' '$CONFIG_USER'"
    log "  created (edit to customize)"
  else
    log "  config.example.yaml missing, skipping"
  fi
fi

log ""
log "=========================="
log "Installation complete!"
log ""
log "Next steps:"
log "  1. Restart Claude Code to pick up the new hook entries"
log "  2. Edit $CONFIG_USER to enable/disable handlers"
log ""
log "To uninstall:  $0 --uninstall"
