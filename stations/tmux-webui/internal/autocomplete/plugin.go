package autocomplete

import (
	"context"
	"os"
	"path/filepath"
	"strings"
)

// PluginScanner walks plugin marketplaces under
// <claudeDir>/plugins/marketplaces/<marketplace>/{external_plugins,plugins}/<plugin>/{skills,commands,agents}/
// and emits Items tagged with their plugin origin.
//
// Both "external_plugins/" and "plugins/" subdir layouts are observed in the
// wild (claude-plugins-official uses "plugins/", openai-codex uses
// "external_plugins/codex/"); we try both per marketplace.
type PluginScanner struct {
	claudeDir string
}

// NewPluginScanner returns a scanner rooted at claudeDir (e.g. "~/.claude").
// The path must already be expanded (no "~").
func NewPluginScanner(claudeDir string) *PluginScanner {
	return &PluginScanner{claudeDir: claudeDir}
}

// Scan implements Scanner. Returns an empty slice if the marketplaces
// directory does not exist.
func (s *PluginScanner) Scan(_ context.Context) []Item {
	root := filepath.Join(s.claudeDir, "plugins", "marketplaces")
	marketplaces, err := os.ReadDir(root)
	if err != nil {
		return nil
	}

	var out []Item
	for _, m := range marketplaces {
		if !m.IsDir() || strings.HasPrefix(m.Name(), ".") {
			continue
		}
		marketDir := filepath.Join(root, m.Name())
		// Both layouts coexist across marketplaces — scan whichever exists.
		for _, layout := range []string{"plugins", "external_plugins"} {
			pluginsRoot := filepath.Join(marketDir, layout)
			plugins, err := os.ReadDir(pluginsRoot)
			if err != nil {
				continue
			}
			for _, p := range plugins {
				if !p.IsDir() || strings.HasPrefix(p.Name(), ".") {
					continue
				}
				out = append(out, s.scanPlugin(filepath.Join(pluginsRoot, p.Name()), m.Name(), p.Name())...)
			}
		}
	}
	return out
}

// scanPlugin reads one plugin's {skills,commands,agents} subdirs and tags
// each item with marketplace + plugin namespace.
func (s *PluginScanner) scanPlugin(pluginDir, marketplace, plugin string) []Item {
	source := "plugin:" + marketplace + ":" + plugin
	var out []Item
	out = append(out, scanPluginSkills(filepath.Join(pluginDir, "skills"), plugin, source)...)
	out = append(out, scanPluginCommands(filepath.Join(pluginDir, "commands"), plugin, source)...)
	out = append(out, scanPluginAgents(filepath.Join(pluginDir, "agents"), plugin, source)...)
	return out
}

func scanPluginSkills(dir, plugin, source string) []Item {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	var out []Item
	for _, e := range entries {
		if !e.IsDir() || strings.HasPrefix(e.Name(), ".") {
			continue
		}
		slug := e.Name()
		fm := parseYAMLFrontmatter(filepath.Join(dir, slug, "SKILL.md"))
		if fm == nil {
			continue
		}
		name := fm["name"]
		if name == "" {
			name = slug
		}
		out = append(out, Item{
			Name:        name,
			DisplayName: plugin + ":" + name,
			Description: pluginDesc(fm["description"]),
			Type:        "skill",
			Icon:        "/",
			Source:      source,
		})
	}
	return out
}

func scanPluginCommands(dir, plugin, source string) []Item {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	var out []Item
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		base := strings.TrimSuffix(e.Name(), ".md")
		fm := parseYAMLFrontmatter(filepath.Join(dir, e.Name()))
		name := fm["name"]
		if name == "" {
			name = base
		}
		out = append(out, Item{
			Name:        name,
			DisplayName: plugin + ":" + name,
			Description: pluginDesc(fm["description"]),
			Type:        "command",
			Icon:        "/",
			Source:      source,
		})
	}
	return out
}

func scanPluginAgents(dir, plugin, source string) []Item {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	var out []Item
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		base := strings.TrimSuffix(e.Name(), ".md")
		fm := parseYAMLFrontmatter(filepath.Join(dir, e.Name()))
		name := fm["name"]
		if name == "" {
			name = base
		}
		var descParts []string
		if m := fm["model"]; m != "" {
			descParts = append(descParts, m)
		}
		if mt := fm["maxTurns"]; mt != "" {
			descParts = append(descParts, "max "+mt+" turns")
		}
		desc := strings.Join(descParts, ", ")
		out = append(out, Item{
			Name:        name,
			DisplayName: plugin + ":" + name,
			Description: pluginDesc(desc),
			Type:        "agent",
			Icon:        "@",
			Source:      source,
		})
	}
	return out
}

// pluginDesc prefixes [plugin] visually so user and plugin items are
// distinguishable in the UI even when the Source field is ignored.
func pluginDesc(raw string) string {
	if raw == "" {
		return "[plugin]"
	}
	return "[plugin] " + truncate(raw, 100)
}
