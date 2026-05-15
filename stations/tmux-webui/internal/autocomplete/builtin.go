package autocomplete

import "context"

// BuiltinScanner emits the curated list of Claude Code built-in slash commands
// — the universally available commands a user can type at any session (not
// loaded from disk, not user-defined). The list is hard-coded because Claude
// Code does not currently expose a discovery API.
//
// Last verified: claude-code 1.x @ 2026-05-15.
// When upgrading Claude Code, cross-check `claude --help` and release notes,
// then bump the date above.
type BuiltinScanner struct{}

// NewBuiltinScanner returns a scanner that always yields the built-in slash
// command roster.
func NewBuiltinScanner() *BuiltinScanner { return &BuiltinScanner{} }

type builtinCmd struct {
	name string // without leading "/"
	desc string
}

var builtinSlashCommands = []builtinCmd{
	{"add-dir", "Add a directory to the current session's working set"},
	{"agents", "Manage subagents and view available agent types"},
	{"bug", "Report a bug to Anthropic"},
	{"clear", "Clear the conversation"},
	{"compact", "Compact conversation history to free context"},
	{"config", "Open Claude Code settings"},
	{"cost", "Show session cost breakdown"},
	{"doctor", "Diagnose the Claude Code installation"},
	{"export", "Export conversation to a file"},
	{"fast", "Toggle fast mode (Opus 4.6+)"},
	{"help", "Show help"},
	{"hooks", "Manage hooks configuration"},
	{"ide", "Open the current session in the IDE extension"},
	{"init", "Initialize CLAUDE.md for the current project"},
	{"login", "Sign in to your Claude account"},
	{"logout", "Sign out of Claude"},
	{"mcp", "Manage MCP servers"},
	{"memory", "Manage persistent memory entries"},
	{"migrate-installer", "Migrate from the npm installer to native binary"},
	{"model", "Switch model (Opus / Sonnet / Haiku)"},
	{"permissions", "Edit tool permissions"},
	{"pr-comments", "Fetch GitHub PR review comments"},
	{"privacy", "Show privacy settings"},
	{"quit", "Exit Claude Code"},
	{"release-notes", "Show release notes"},
	{"resume", "Resume a previous session"},
	{"review", "Review pending code changes"},
	{"security-review", "Run a security review on pending changes"},
	{"statusline", "Configure the status line"},
	{"todos", "Show the todo list"},
	{"upgrade", "Upgrade Claude Code to the latest version"},
	{"vim", "Toggle vim mode"},
}

// Scan implements Scanner.
func (s *BuiltinScanner) Scan(_ context.Context) []Item {
	out := make([]Item, 0, len(builtinSlashCommands))
	for _, c := range builtinSlashCommands {
		out = append(out, Item{
			Name:        c.name,
			DisplayName: "/" + c.name,
			Description: c.desc,
			Type:        "builtin",
			Icon:        "/",
			Source:      "builtin",
		})
	}
	return out
}
