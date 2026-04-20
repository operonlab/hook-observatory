// Package handlers — session_namer.go
// Stop + UserPromptSubmit handler — session auto-namer + color hint.
//
// On the first Stop event of a session, spawns a background Python process that:
//  1. Reads the session transcript to get the first user message
//  2. Calls Haiku via claude CLI to generate a 2-4 word kebab-case title + color
//  3. Stores in ~/.claude/data/session-titles.json (external registry)
//
// On UserPromptSubmit, if a color has been assigned but not yet applied,
// injects a one-time hint so the model can suggest /color <name>.
//
// Non-blocking: spawns background process, returns Allow immediately.
// Fail-open: any error -> silently skip, never block Claude Code.
package handlers

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/joneshong/hook-dispatcher/internal/core"
)

var sessionNamerValidColors = map[string]struct{}{
	"red": {}, "blue": {}, "green": {}, "yellow": {},
	"purple": {}, "orange": {}, "pink": {}, "cyan": {},
}

func init() {
	core.Register("Stop", core.Entry{
		Matcher:    "",
		Handler:    sessionNamerHandle,
		Critical:   false,
		ModuleName: "session_namer",
	})
	core.Register("UserPromptSubmit", core.Entry{
		Matcher:    "",
		Handler:    sessionNamerHandleColorHint,
		Critical:   false,
		ModuleName: "session_namer",
	})
}

// sessionNamerHandle names the session on the first Stop event (non-blocking).
func sessionNamerHandle(_, _ string, _ map[string]any, rawInput string) core.HookResult {
	if os.Getenv("CLAUDE_SESSION_NAMER") == "0" {
		return core.Allow()
	}

	sessionID := os.Getenv("CLAUDE_SESSION_ID")
	if sessionID == "" {
		if strings.TrimSpace(rawInput) != "" {
			var parsed map[string]any
			if err := json.Unmarshal([]byte(rawInput), &parsed); err == nil {
				sessionID, _ = parsed["session_id"].(string)
			}
		}
	}
	if sessionID == "" {
		return core.Allow()
	}

	// Already named? Skip.
	if sessionNamerIsNamed(sessionID) {
		return core.Allow()
	}

	home, _ := os.UserHomeDir()
	python := filepath.Join(home, ".local", "bin", "python3")

	// Build background Python code — mirrors session_namer.py background worker
	code := sessionNamerBuildCode(sessionID, home)
	_ = core.RunBackground([]string{python, "-c", code}, "")

	return core.Allow()
}

// sessionNamerHandleColorHint injects a one-time color hint on UserPromptSubmit.
func sessionNamerHandleColorHint(_, _ string, _ map[string]any, _ string) core.HookResult {
	if os.Getenv("CLAUDE_SESSION_NAMER") == "0" {
		return core.Allow()
	}

	sessionID := os.Getenv("CLAUDE_SESSION_ID")
	if sessionID == "" {
		return core.Allow()
	}

	marker := fmt.Sprintf("/tmp/.claude-color-hinted-%s", sessionID)
	if _, err := os.Stat(marker); err == nil {
		// Already hinted
		return core.Allow()
	}

	registry := sessionNamerLoadRegistry()
	entry, ok := registry[sessionID]
	if !ok {
		return core.Allow()
	}
	entryMap, ok := entry.(map[string]any)
	if !ok {
		return core.Allow()
	}
	color, _ := entryMap["color"].(string)

	if _, valid := sessionNamerValidColors[color]; !valid || color == "" {
		return core.Allow()
	}

	// Write marker — hint only once per session
	_ = os.WriteFile(marker, []byte(color), 0o644)
	return core.TextResult(fmt.Sprintf("Session color assigned: %s — suggest user run `/color %s`", color, color))
}

func sessionNamerIsNamed(sessionID string) bool {
	registry := sessionNamerLoadRegistry()
	_, exists := registry[sessionID]
	return exists
}

func sessionNamerLoadRegistry() map[string]any {
	home, _ := os.UserHomeDir()
	registryPath := filepath.Join(home, ".claude", "data", "session-titles.json")
	data, err := os.ReadFile(registryPath)
	if err != nil {
		return map[string]any{}
	}
	var registry map[string]any
	if err := json.Unmarshal(data, &registry); err != nil {
		return map[string]any{}
	}
	return registry
}

// sessionNamerBuildCode builds the Python background worker code.
// This mirrors the Python implementation exactly — spawning claude CLI to generate the title.
func sessionNamerBuildCode(sessionID, home string) string {
	registryPath := filepath.Join(home, ".claude", "data", "session-titles.json")

	return `import os, sys, json, glob, fcntl
from datetime import datetime, timezone

HOME = os.path.expanduser('~')
REGISTRY = ` + fmt.Sprintf("%q", registryPath) + `
session_id = ` + fmt.Sprintf("%q", sessionID) + `

# Find transcript
pattern = os.path.join(HOME, '.claude', 'projects', '**', f'{session_id}.jsonl')
matches = glob.glob(pattern, recursive=True)
if not matches:
    sys.exit(0)

# Extract first user message
first_message = ''
try:
    with open(matches[0]) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            msg_obj = entry.get('message', {}) or {}
            role = entry.get('type', '') or msg_obj.get('role', '')
            if role == 'user':
                msg = msg_obj
                content = msg.get('content', '')
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'text':
                            first_message = block.get('text', '')
                            break
                elif isinstance(content, str):
                    first_message = content
                if first_message:
                    break
except Exception:
    sys.exit(0)

if not first_message.strip():
    sys.exit(0)

# Call Haiku via claude CLI (inherits OAuth auth)
import subprocess as _sp
try:
    prompt = ('Generate a session title and pick a prompt-bar color.\n'
              'Title: 2-4 word kebab-case, verb-first, max 30 chars.\n'
              'Color: pick ONE from [red,blue,green,yellow,purple,orange,pink,cyan] '
              'that matches the task mood/domain.\n'
              'Return ONLY JSON: {"title":"...","color":"..."}\n\n'
              f'User message: {first_message[:500]}')
    r = _sp.run(
        ['claude', '-p', prompt, '--model', 'haiku', '--output-format', 'text',
         '--no-session-persistence'],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, 'CTX_SUPERVISOR_LEVEL': 'off',
             'CLAUDE_SESSION_NAMER': '0'},
    )
    raw = r.stdout.strip()
    import re as _re
    m = _re.search(r'\{[^}]*"title"[^}]*\}', raw)
    if m:
        raw = m.group()
    try:
        parsed = json.loads(raw)
        title = parsed.get('title', '').strip()
        color = parsed.get('color', '').strip().lower()
    except Exception:
        title = raw.strip()
        color = ''
    valid = {'red','blue','green','yellow','purple','orange','pink','cyan'}
    if color not in valid:
        color = ''
except Exception:
    sys.exit(0)

if not title:
    sys.exit(0)

# Write to registry with file lock
os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
try:
    with open(REGISTRY, 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        content = f.read().strip()
        registry = json.loads(content) if content else {}
        created = datetime.now(timezone.utc).isoformat()
        registry[session_id] = {
            'title': title, 'color': color, 'created_at': created}
        f.seek(0)
        f.truncate()
        json.dump(registry, f, indent=2)
        fcntl.flock(f, fcntl.LOCK_UN)
except Exception:
    pass
`
}
