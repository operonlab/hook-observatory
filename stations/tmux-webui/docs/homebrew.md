# Install via Homebrew

`tmux-webui` is published in the `operonlab/tap` Homebrew tap.

## One-liner

```sh
brew install operonlab/tap/tmux-webui
```

This auto-taps `operonlab/tap` if needed and pulls the bottle.

## Two-step (manual tap)

```sh
brew tap operonlab/tap
brew install tmux-webui
```

## Verify

```sh
tmux-webui version
```

## Update

Homebrew handles updates:

```sh
brew update
brew upgrade tmux-webui
```

> `tmux-webui update` (the built-in self-updater) also works for Homebrew installs, but Homebrew is preferred so the package manager stays in sync.

## Why a tap and not homebrew-core?

`tmux-webui` is small and moves fast. A tap lets us cut releases without going through the homebrew-core review queue. Once the tool stabilizes, we may submit to homebrew-core.

## What the formula installs

- The `tmux-webui` binary
- A dependency on `tmux` (Homebrew installs it if missing)

It does **not**:
- start a daemon (use `tmux-webui daemon install` if you want one)
- write any config (the binary auto-creates `~/.config/tmux-webui/config.json` on first run)

## Uninstall via Homebrew

```sh
brew uninstall tmux-webui
brew untap operonlab/tap   # optional
```

For the full purge (config + uploads + daemon), also run `tmux-webui uninstall -y` *before* `brew uninstall`.
