# hook-observatory Installer

## Directory
`installer/` — 6-step guided wizard

## Pages
1. Welcome — centered card
2. DependencyCheck — 3-col grid (python, claude_code, git)
3. ComponentSelect — category groups with checkbox cards
4. ToolConfig — Python path input + 4 tool cards (git, ruff, biome, gh)
5. Installing — progress steps with spinner
6. Complete — success checkmark + close button

## Key Types
- `ToolDetailInfo`: name, path, version, installed, install_command, required
- `ToolPaths`: python, ruff, biome (used by install process)
- Rust `detect_tools()` returns 5 tools: python, git, ruff, biome, gh

## Window
- minWidth: 600, minHeight: 400
