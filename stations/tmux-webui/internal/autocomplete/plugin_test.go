package autocomplete

// plugin_test.go — unit tests for PluginScanner.
//
// Mutation-thinking risk list:
//  1. marketplaces dir missing → Scan returns nil (no panic)
//  2. Empty marketplace with neither plugins/ nor external_plugins/ → no items
//  3. Both layouts coexist in one marketplace → both are scanned
//  4. Plugin skill missing SKILL.md → skipped, not crashed
//  5. Plugin command non-.md file in commands/ → skipped
//  6. Plugin agent gets description from model + maxTurns
//  7. DisplayName format is "<plugin>:<name>"
//  8. Source format is "plugin:<marketplace>:<plugin>"
//  9. pluginDesc prefixes "[plugin]" and truncates at 100 runes
// 10. Hidden dot-directories (.codex, .git) at marketplace and plugin level are skipped

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// ─── helpers ──────────────────────────────────────────────────────────────────

// writeFile writes content to path, creating parent dirs as needed.
func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

// claudeDirWith builds <tmp>/.claude/plugins/marketplaces/<paths…> fixtures.
// Returns the claudeDir root to pass to NewPluginScanner.
func claudeDirWith(t *testing.T) string {
	t.Helper()
	root := filepath.Join(t.TempDir(), ".claude")
	if err := os.MkdirAll(filepath.Join(root, "plugins", "marketplaces"), 0o755); err != nil {
		t.Fatal(err)
	}
	return root
}

// findItem returns the first Item whose Name + Type match, or nil.
func findItem(items []Item, name, typ string) *Item {
	for i := range items {
		if items[i].Name == name && items[i].Type == typ {
			return &items[i]
		}
	}
	return nil
}

// ─── tests ────────────────────────────────────────────────────────────────────

func TestPluginScanner_MissingRoot_NoCrash(t *testing.T) {
	s := NewPluginScanner(filepath.Join(t.TempDir(), "does-not-exist"))
	if got := s.Scan(context.Background()); got != nil {
		t.Errorf("Scan with missing root = %v; want nil", got)
	}
}

func TestPluginScanner_EmptyMarketplace_NoItems(t *testing.T) {
	claudeDir := claudeDirWith(t)
	if err := os.MkdirAll(filepath.Join(claudeDir, "plugins", "marketplaces", "empty"), 0o755); err != nil {
		t.Fatal(err)
	}
	items := NewPluginScanner(claudeDir).Scan(context.Background())
	if len(items) != 0 {
		t.Errorf("empty marketplace yielded %d items; want 0", len(items))
	}
}

func TestPluginScanner_BothLayoutsCoexist(t *testing.T) {
	claudeDir := claudeDirWith(t)
	base := filepath.Join(claudeDir, "plugins", "marketplaces", "mkt-a")

	// plugins/ layout — one skill
	writeFile(t,
		filepath.Join(base, "plugins", "alpha", "skills", "draw", "SKILL.md"),
		"---\nname: draw\ndescription: Draw something\n---\n# Draw\n")

	// external_plugins/ layout — one command
	writeFile(t,
		filepath.Join(base, "external_plugins", "beta", "commands", "ship.md"),
		"---\nname: ship\ndescription: Ship a release\n---\n## Body\n")

	items := NewPluginScanner(claudeDir).Scan(context.Background())
	if len(items) != 2 {
		t.Fatalf("expected 2 items across both layouts, got %d: %+v", len(items), items)
	}

	skill := findItem(items, "draw", "skill")
	if skill == nil {
		t.Fatal("missing 'draw' skill item")
	}
	if skill.DisplayName != "alpha:draw" {
		t.Errorf("DisplayName = %q; want %q", skill.DisplayName, "alpha:draw")
	}
	if skill.Source != "plugin:mkt-a:alpha" {
		t.Errorf("Source = %q; want %q", skill.Source, "plugin:mkt-a:alpha")
	}
	if !strings.HasPrefix(skill.Description, "[plugin] ") {
		t.Errorf("Description = %q; want [plugin] prefix", skill.Description)
	}

	cmd := findItem(items, "ship", "command")
	if cmd == nil {
		t.Fatal("missing 'ship' command item")
	}
	if cmd.DisplayName != "beta:ship" {
		t.Errorf("cmd DisplayName = %q; want %q", cmd.DisplayName, "beta:ship")
	}
}

func TestPluginScanner_SkipsHiddenDirs(t *testing.T) {
	claudeDir := claudeDirWith(t)

	// Hidden marketplace must be ignored.
	writeFile(t,
		filepath.Join(claudeDir, "plugins", "marketplaces", ".git", "plugins", "x", "skills", "y", "SKILL.md"),
		"---\nname: y\n---\n")
	// Hidden plugin dir inside a real marketplace must be ignored.
	writeFile(t,
		filepath.Join(claudeDir, "plugins", "marketplaces", "real", "plugins", ".hidden", "skills", "z", "SKILL.md"),
		"---\nname: z\n---\n")

	items := NewPluginScanner(claudeDir).Scan(context.Background())
	for _, it := range items {
		if strings.HasPrefix(it.Source, "plugin:.git:") || strings.HasPrefix(it.DisplayName, ".hidden:") {
			t.Errorf("hidden dir leaked into items: %+v", it)
		}
	}
}

func TestPluginScanner_SkillWithoutSkillMD_Skipped(t *testing.T) {
	claudeDir := claudeDirWith(t)
	// Skill dir exists but no SKILL.md → must be skipped (parseYAMLFrontmatter → nil).
	skillDir := filepath.Join(claudeDir, "plugins", "marketplaces", "m", "plugins", "p", "skills", "ghost")
	if err := os.MkdirAll(skillDir, 0o755); err != nil {
		t.Fatal(err)
	}

	items := NewPluginScanner(claudeDir).Scan(context.Background())
	if len(items) != 0 {
		t.Errorf("got %d items for skill without SKILL.md; want 0", len(items))
	}
}

func TestPluginScanner_AgentDescription_FromModelAndMaxTurns(t *testing.T) {
	claudeDir := claudeDirWith(t)
	writeFile(t,
		filepath.Join(claudeDir, "plugins", "marketplaces", "m", "plugins", "p", "agents", "scout.md"),
		"---\nname: scout\nmodel: sonnet\nmaxTurns: 10\n---\n")

	items := NewPluginScanner(claudeDir).Scan(context.Background())
	agent := findItem(items, "scout", "agent")
	if agent == nil {
		t.Fatal("missing 'scout' agent")
	}
	// pluginDesc prefixes "[plugin] " then includes the truncated raw desc.
	want := "[plugin] sonnet, max 10 turns"
	if agent.Description != want {
		t.Errorf("agent.Description = %q; want %q", agent.Description, want)
	}
	if agent.Icon != "@" {
		t.Errorf("agent.Icon = %q; want @", agent.Icon)
	}
}

func TestPluginScanner_CommandNonMD_Ignored(t *testing.T) {
	claudeDir := claudeDirWith(t)
	cmdsDir := filepath.Join(claudeDir, "plugins", "marketplaces", "m", "plugins", "p", "commands")
	writeFile(t, filepath.Join(cmdsDir, "real.md"), "---\nname: real\n---\n")
	writeFile(t, filepath.Join(cmdsDir, "README.txt"), "not a command")
	writeFile(t, filepath.Join(cmdsDir, ".DS_Store"), "junk")

	items := NewPluginScanner(claudeDir).Scan(context.Background())
	var commands []Item
	for _, it := range items {
		if it.Type == "command" {
			commands = append(commands, it)
		}
	}
	if len(commands) != 1 || commands[0].Name != "real" {
		t.Errorf("commands = %+v; want one entry named 'real'", commands)
	}
}

func TestPluginDesc_PrefixAndTruncate(t *testing.T) {
	long := strings.Repeat("a", 200)
	got := pluginDesc(long)
	if !strings.HasPrefix(got, "[plugin] ") {
		t.Errorf("missing prefix: %q", got[:20])
	}
	// "[plugin] " + 100 runes = 109
	if len([]rune(got)) != len([]rune("[plugin] "))+100 {
		t.Errorf("truncation off: rune len = %d", len([]rune(got)))
	}
	if pluginDesc("") != "[plugin]" {
		t.Errorf("empty desc = %q; want %q", pluginDesc(""), "[plugin]")
	}
}
