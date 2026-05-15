# Autocomplete coverage

`internal/autocomplete` matches what a user types in the tmux-webui input bar
against the full Claude Code resource universe — user-level resources, plugin
marketplace resources, and Claude Code's built-in slash commands.

## Sources

| Source | Scanner | Type values produced | Items on a representative install |
|---|---|---|---:|
| `~/.claude/{skills,commands,agents}` | `ClaudeDirScanner` | `skill`, `command`, `agent` | ~70 |
| `~/.claude/settings.json` → `mcpServers` | `ClaudeDirScanner` | `mcp` | 0–N |
| `~/.claude/plugins/marketplaces/<m>/{external_plugins,plugins}/<p>/{skills,commands,agents}/` | `PluginScanner` | `skill`, `command`, `agent` | ~190 |
| Hard-coded Claude Code slash roster | `BuiltinScanner` | `builtin` | 32 |

All sources flow through the same `Scanner` interface; the `ResourceCache`
runs them in order and concatenates results.

## Scanner notes

### `ClaudeDirScanner`
Reads YAML frontmatter (4 KB cap) from every `SKILL.md`, `commands/*.md`, and
`agents/*.md`. Falls back to first `# header` and first paragraph when
frontmatter is absent. Tested for missing files, malformed JSON, quoted/block
scalar YAML.

### `PluginScanner`
Marketplaces use one of two layouts depending on origin
(`claude-plugins-official` uses `plugins/`, `openai-codex` uses
`external_plugins/`); both are scanned per marketplace. Hidden dot-directories
(`.git`, `.codex`) at marketplace and plugin level are skipped — these are
build artifacts, not real plugins.

Naming convention for plugin items:

- `Item.Name` — raw slug, so fuzzy matching behaves like a user-level item
- `Item.DisplayName` — `<plugin>:<name>` (two layers; legible on phones)
- `Item.Source` — `plugin:<marketplace>:<plugin>` (three layers; full provenance)
- `Item.Description` — original frontmatter description, prefixed `[plugin] ` and truncated to 100 runes

User-level items keep `Source == ""` (empty); built-ins set `Source == "builtin"`.

### `BuiltinScanner`
Hard-coded list of 32 slash commands (`/compact`, `/model`, `/clear`, …) —
Claude Code does not yet expose a discovery API for these. The list lives at
the top of `internal/autocomplete/builtin.go` with a `Last verified` comment.

**Maintenance**: when upgrading Claude Code, run `claude --help` and review
release notes; add new commands, remove dropped ones, bump the `Last
verified` date. `TestBuiltinScanner_CoreCommandsPresent` guards against
accidentally dropping daily-drivers (`compact`, `model`, `clear`, `help`,
`agents`, `mcp`, `hooks`, `cost`).

## Ranking

`slashItems()` returns items in fixed order: builtins → user → plugins.
`fuzzy.rankAndFilter()` then sorts by score; this ordering matters only when
scores tie — in which case the well-known Claude Code slash command wins
over a user skill, which wins over a plugin item. There is no deduplication:
if a user and a plugin both define `frontend-design`, both appear and the
`[plugin]` prefix in the description disambiguates visually.

## Routing

`Complete(query, typeFilter)` dispatches by trigger character or explicit
`typeFilter`:

- `typeFilter == "path"` → path completion
- query starts with `/`, or `typeFilter ∈ {skill, command, builtin}` → slash items
- query starts with `@`, or `typeFilter == "at"` → agents + MCP servers
- query starts with `~/`, `./`, or contains `/` → path completion

## Wire-up

`server.go`:

```go
ac := autocomplete.New(autocomplete.Options{
    ClaudeDir:       cfg.Autocomplete.ClaudeDir,
    IncludePlugins:  true,
    IncludeBuiltins: true,
})
```

`ClaudeDir` gates plugins (plugins live under `<ClaudeDir>/plugins/...`); a
tmux-webui not pointed at `~/.claude` degrades to builtins + path completion
only. Cache refresh runs every 5 minutes; `/api/autocomplete/refresh` forces
an immediate scan.

## History

Pre-2026-Q2 the autocomplete engine was a 1:1 Go port of an earlier Python
module that only covered user-level resources — plugins (~196 items) and
built-in slash commands (~32) were absent. The `PluginScanner` and
`BuiltinScanner` were added together with the multi-`Scanner` cache
refactor; user-level scanner code did not change.
