// Package handlers — schedule_sync.go
// PostToolUse handler for Edit/Write on schedules/manifest.json.
// Detects changes to schedules/manifest.json and triggers background sync.
//
// Go in-process port:
//   - Reads manifest.json + registry.json, diffs enabled jobs.
//   - For each added job: writes a launchd plist, execs `launchctl load`,
//     and appends to registry.json.
//   - For each removed job: execs `launchctl unload`, deletes plist,
//     rewrites registry.json without the entry.
//   - Replaces the python3 scheduler.py fork — pure Go except for the
//     mandatory `launchctl` invocation.
package handlers

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/joneshong/hook-observatory/internal/core"
)

func init() {
	core.Register("PostToolUse", core.Entry{
		Matcher:    "Edit|Write",
		Handler:    scheduleSyncHandle,
		Critical:   false,
		ModuleName: "schedule_sync",
	})
}

const (
	scheduleSyncLabelPrefix = "com.joneshong.scheduler."
)

func scheduleSyncHandle(_, _ string, toolInput map[string]any, _ string) core.HookResult {
	filePath, _ := toolInput["file_path"].(string)
	if !strings.Contains(filePath, "schedules/manifest.json") {
		return core.Allow()
	}

	go scheduleSyncInProc()
	return core.Allow()
}

// ---------------------------------------------------------------------------
// In-process sync logic
// ---------------------------------------------------------------------------

func scheduleSyncInProc() {
	home, err := os.UserHomeDir()
	if err != nil {
		return
	}

	workshop := filepath.Join(home, "workshop")
	manifestPath := filepath.Join(workshop, "schedules", "manifest.json")
	registryDir, err := scheduleSyncRegistryDir()
	if err != nil {
		return
	}
	registryPath := filepath.Join(registryDir, "registry.json")

	manifestNames, err := scheduleSyncLoadManifest(manifestPath)
	if err != nil {
		scheduleSyncLog(fmt.Sprintf("manifest read error: %v", err))
		return
	}

	registryNames := scheduleSyncLoadRegistry(registryPath) // best-effort; empty slice on error

	registrySet := make(map[string]bool, len(registryNames))
	for _, n := range registryNames {
		registrySet[n] = true
	}
	manifestSet := make(map[string]bool, len(manifestNames))
	for _, n := range manifestNames {
		manifestSet[n] = true
	}

	var toAdd, toRemove []string
	for _, n := range manifestNames {
		if !registrySet[n] {
			toAdd = append(toAdd, n)
		}
	}
	for _, n := range registryNames {
		if !manifestSet[n] {
			toRemove = append(toRemove, n)
		}
	}

	if len(toAdd) == 0 && len(toRemove) == 0 {
		scheduleSyncLog("already in sync — no changes needed")
		return
	}

	allJobs, _ := scheduleSyncLoadManifestFull(manifestPath)

	for _, name := range toRemove {
		scheduleSyncLog(fmt.Sprintf("remove: %s", name))
		if err := scheduleSyncRemoveJob(name); err != nil {
			scheduleSyncLog(fmt.Sprintf("remove %s failed: %v", name, err))
		}
	}

	for _, name := range toAdd {
		job, ok := allJobs[name]
		if !ok {
			scheduleSyncLog(fmt.Sprintf("skip add %s — not found in manifest", name))
			continue
		}
		command, _ := job["command"].(string)
		description, _ := job["description"].(string)
		schedule := scheduleSyncBuildSchedule(job)

		scheduleSyncLog(fmt.Sprintf("add: %s → %s", name, command))
		if err := scheduleSyncAddJob(name, command, schedule, description); err != nil {
			scheduleSyncLog(fmt.Sprintf("add %s failed: %v", name, err))
		}
	}

	scheduleSyncLog(fmt.Sprintf("sync complete: +%d -%d", len(toAdd), len(toRemove)))
}

// ---------------------------------------------------------------------------
// launchd operations (replaces scheduler.py add_job / remove_job)
// ---------------------------------------------------------------------------

// scheduleSyncRegistryDir resolves the scheduler data directory, honouring
// the same SCHEDULER_DATA_DIR env override that scheduler.py reads.
func scheduleSyncRegistryDir() (string, error) {
	if v := os.Getenv("SCHEDULER_DATA_DIR"); v != "" {
		return v, nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, "workshop", "outputs", "scheduler"), nil
}

// scheduleSyncAddJob mirrors scheduler.py `add_job`.
func scheduleSyncAddJob(name, command string, schedule map[string]any, description string) error {
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}

	label := scheduleSyncLabelPrefix + name
	registryDir, err := scheduleSyncRegistryDir()
	if err != nil {
		return err
	}
	logDir := filepath.Join(registryDir, "logs")
	launchAgentsDir := filepath.Join(home, "Library", "LaunchAgents")
	plistFile := filepath.Join(launchAgentsDir, label+".plist")
	registryFile := filepath.Join(registryDir, "registry.json")

	if err := os.MkdirAll(registryDir, 0o755); err != nil {
		return err
	}
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return err
	}
	if err := os.MkdirAll(launchAgentsDir, 0o755); err != nil {
		return err
	}

	entries := scheduleSyncReadRegistry(registryFile)
	for _, e := range entries {
		if n, _ := e["name"].(string); n == name {
			return fmt.Errorf("job %q already exists", name)
		}
	}

	plistDict := map[string]any{
		"Label":             label,
		"ProgramArguments":  []string{"/bin/zsh", "-lc", command},
		"StandardOutPath":   filepath.Join(logDir, name+".log"),
		"StandardErrorPath": filepath.Join(logDir, name+".err"),
	}

	if v, ok := schedule["interval"]; ok {
		if i, ok := scheduleSyncToInt(v); ok {
			plistDict["StartInterval"] = i
		}
	} else if cal, ok := schedule["calendar"].(map[string]any); ok {
		calInt := make(map[string]any, len(cal))
		for k, v := range cal {
			if i, ok := scheduleSyncToInt(v); ok {
				calInt[k] = i
			}
		}
		plistDict["StartCalendarInterval"] = calInt
	}

	if b, _ := schedule["run_at_load"].(bool); b {
		plistDict["RunAtLoad"] = true
	}

	if b, _ := schedule["keep_alive"].(bool); b {
		plistDict["KeepAlive"] = true
		throttle := 10
		if v, ok := schedule["throttle_interval"]; ok {
			if i, ok := scheduleSyncToInt(v); ok {
				throttle = i
			}
		}
		plistDict["ThrottleInterval"] = throttle
	}

	plistXML := scheduleSyncEncodePlist(plistDict)
	if err := os.WriteFile(plistFile, []byte(plistXML), 0o644); err != nil {
		return fmt.Errorf("write plist: %w", err)
	}

	// launchctl load — best-effort (matches scheduler.py which ignores errors).
	_ = core.RunCmd([]string{"launchctl", "load", plistFile}, "", 10*time.Second, "")

	entry := map[string]any{
		"name":        name,
		"label":       label,
		"command":     command,
		"schedule":    schedule,
		"description": description,
		"plist":       plistFile,
		"enabled":     true,
		"created":     scheduleSyncNowISO(),
	}
	entries = append(entries, entry)
	return scheduleSyncWriteRegistry(registryFile, entries)
}

// scheduleSyncRemoveJob mirrors scheduler.py `remove_job`.
func scheduleSyncRemoveJob(name string) error {
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	registryDir, err := scheduleSyncRegistryDir()
	if err != nil {
		return err
	}
	registryFile := filepath.Join(registryDir, "registry.json")
	launchAgentsDir := filepath.Join(home, "Library", "LaunchAgents")

	entries := scheduleSyncReadRegistry(registryFile)
	var entry map[string]any
	remaining := make([]map[string]any, 0, len(entries))
	for _, e := range entries {
		if n, _ := e["name"].(string); n == name {
			entry = e
			continue
		}
		remaining = append(remaining, e)
	}
	if entry == nil {
		return fmt.Errorf("job %q not found", name)
	}

	plistFile, _ := entry["plist"].(string)
	if plistFile == "" {
		plistFile = filepath.Join(launchAgentsDir, scheduleSyncLabelPrefix+name+".plist")
	}
	if _, err := os.Stat(plistFile); err == nil {
		_ = core.RunCmd([]string{"launchctl", "unload", plistFile}, "", 10*time.Second, "")
		_ = os.Remove(plistFile)
	}

	return scheduleSyncWriteRegistry(registryFile, remaining)
}

// ---------------------------------------------------------------------------
// Manifest / registry helpers
// ---------------------------------------------------------------------------

// scheduleSyncLoadManifest returns names of enabled jobs.
func scheduleSyncLoadManifest(path string) ([]string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var manifest struct {
		Jobs []map[string]any `json:"jobs"`
	}
	if err := json.Unmarshal(data, &manifest); err != nil {
		return nil, err
	}
	var names []string
	for _, job := range manifest.Jobs {
		enabled, _ := job["enabled"].(bool)
		if !enabled {
			continue
		}
		name, _ := job["name"].(string)
		if name != "" {
			names = append(names, name)
		}
	}
	return names, nil
}

// scheduleSyncLoadManifestFull returns a map[name]→job for all enabled jobs.
func scheduleSyncLoadManifestFull(path string) (map[string]map[string]any, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var manifest struct {
		Jobs []map[string]any `json:"jobs"`
	}
	if err := json.Unmarshal(data, &manifest); err != nil {
		return nil, err
	}
	result := make(map[string]map[string]any)
	for _, job := range manifest.Jobs {
		enabled, _ := job["enabled"].(bool)
		if !enabled {
			continue
		}
		name, _ := job["name"].(string)
		if name != "" {
			result[name] = job
		}
	}
	return result, nil
}

// scheduleSyncLoadRegistry returns job names from registry.json (best-effort).
func scheduleSyncLoadRegistry(path string) []string {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var entries []map[string]any
	if err := json.Unmarshal(data, &entries); err != nil {
		return nil
	}
	var names []string
	for _, entry := range entries {
		if name, ok := entry["name"].(string); ok && name != "" {
			names = append(names, name)
		}
	}
	return names
}

// scheduleSyncBuildSchedule copies the schedule dict and applies the
// daemon→keep_alive default (matches sync.py / scheduler.py behaviour).
func scheduleSyncBuildSchedule(job map[string]any) map[string]any {
	raw, _ := job["schedule"].(map[string]any)
	out := make(map[string]any, len(raw)+1)
	for k, v := range raw {
		out[k] = v
	}
	if jobType, _ := job["type"].(string); jobType == "daemon" {
		if _, has := out["keep_alive"]; !has {
			out["keep_alive"] = true
		}
	}
	return out
}

func scheduleSyncReadRegistry(path string) []map[string]any {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var entries []map[string]any
	if err := json.Unmarshal(data, &entries); err != nil {
		return nil
	}
	return entries
}

func scheduleSyncWriteRegistry(path string, entries []map[string]any) error {
	if entries == nil {
		entries = []map[string]any{}
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	if err := enc.Encode(entries); err != nil {
		return err
	}
	// json.Encoder appends a trailing newline; Python's json.dumps does not.
	out := bytes.TrimRight(buf.Bytes(), "\n")
	return os.WriteFile(path, out, 0o644)
}

func scheduleSyncToInt(v any) (int, bool) {
	switch x := v.(type) {
	case int:
		return x, true
	case int64:
		return int(x), true
	case float64:
		return int(x), true
	case json.Number:
		i, err := x.Int64()
		if err == nil {
			return int(i), true
		}
	}
	return 0, false
}

func scheduleSyncNowISO() string {
	return time.Now().Format("2006-01-02T15:04:05.000000")
}

// ---------------------------------------------------------------------------
// plist XML encoder (limited to types used by scheduler.py)
// ---------------------------------------------------------------------------

func scheduleSyncEncodePlist(d map[string]any) string {
	var sb strings.Builder
	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>` + "\n")
	sb.WriteString(`<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">` + "\n")
	sb.WriteString(`<plist version="1.0">` + "\n")
	scheduleSyncEncodeDict(&sb, d, 0)
	sb.WriteString("</plist>\n")
	return sb.String()
}

func scheduleSyncEncodeDict(sb *strings.Builder, d map[string]any, indent int) {
	tab := strings.Repeat("\t", indent)
	sb.WriteString(tab + "<dict>\n")
	keys := make([]string, 0, len(d))
	for k := range d {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	innerTab := strings.Repeat("\t", indent+1)
	for _, k := range keys {
		sb.WriteString(innerTab + "<key>" + scheduleSyncXMLEscape(k) + "</key>\n")
		scheduleSyncEncodeValue(sb, d[k], indent+1)
	}
	sb.WriteString(tab + "</dict>\n")
}

func scheduleSyncEncodeValue(sb *strings.Builder, v any, indent int) {
	tab := strings.Repeat("\t", indent)
	switch vv := v.(type) {
	case bool:
		if vv {
			sb.WriteString(tab + "<true/>\n")
		} else {
			sb.WriteString(tab + "<false/>\n")
		}
	case int:
		sb.WriteString(tab + fmt.Sprintf("<integer>%d</integer>\n", vv))
	case int64:
		sb.WriteString(tab + fmt.Sprintf("<integer>%d</integer>\n", vv))
	case float64:
		sb.WriteString(tab + fmt.Sprintf("<integer>%d</integer>\n", int64(vv)))
	case string:
		sb.WriteString(tab + "<string>" + scheduleSyncXMLEscape(vv) + "</string>\n")
	case []string:
		sb.WriteString(tab + "<array>\n")
		inner := strings.Repeat("\t", indent+1)
		for _, s := range vv {
			sb.WriteString(inner + "<string>" + scheduleSyncXMLEscape(s) + "</string>\n")
		}
		sb.WriteString(tab + "</array>\n")
	case []any:
		sb.WriteString(tab + "<array>\n")
		for _, item := range vv {
			scheduleSyncEncodeValue(sb, item, indent+1)
		}
		sb.WriteString(tab + "</array>\n")
	case map[string]any:
		scheduleSyncEncodeDict(sb, vv, indent)
	}
}

// scheduleSyncXMLEscape escapes element-content characters the same way
// Python's plistlib does: only `<`, `>`, and `&`.
func scheduleSyncXMLEscape(s string) string {
	var sb strings.Builder
	sb.Grow(len(s))
	for _, r := range s {
		switch r {
		case '<':
			sb.WriteString("&lt;")
		case '>':
			sb.WriteString("&gt;")
		case '&':
			sb.WriteString("&amp;")
		default:
			sb.WriteRune(r)
		}
	}
	return sb.String()
}

func scheduleSyncLog(msg string) {
	ts := time.Now().Format("15:04:05")
	fmt.Fprintf(os.Stderr, "[schedule-sync] %s %s\n", ts, msg)
}
