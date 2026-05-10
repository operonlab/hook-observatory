# Uninstall tmux-webui

```sh
tmux-webui uninstall -y
```

What this removes:

| Path | What |
|------|------|
| `~/Library/LaunchAgents/dev.tmux-webui.plist` (macOS) | daemon unit |
| `~/.config/systemd/user/tmux-webui.service` (Linux) | daemon unit |
| `~/.config/tmux-webui/` | config |
| `<UserCacheDir>/tmux-webui/` | uploads + logs |
| `$(command -v tmux-webui)` | the binary itself |

## Edge cases

- **Binary in `/usr/local/bin` owned by root**: the uninstall command will print a fallback line:
  ```
  warning: could not remove /usr/local/bin/tmux-webui: permission denied
          you may need: sudo rm /usr/local/bin/tmux-webui
  ```
  Run the suggested `sudo rm` to finish cleanup.

- **Installed via Homebrew**: the binary lives at `/opt/homebrew/bin/tmux-webui`. Run:
  ```sh
  brew uninstall tmux-webui
  brew untap operonlab/tap   # optional
  ```

## Not removed

`tmux-webui uninstall` does **not** remove tmux itself (you may still use tmux for other things) or any tmux sessions you have running.

## Manual cleanup checklist

If you'd rather not run `uninstall` for any reason:

```sh
# 1. Stop daemon
tmux-webui daemon uninstall   # if you set it up

# 2. Remove paths
rm -rf ~/.config/tmux-webui
rm -rf "$(go env GOPATH)/bin/tmux-webui"     # if you `go install`-ed
rm -rf ~/.local/bin/tmux-webui                 # if you used install.sh
rm -rf "$(getconf DARWIN_USER_CACHE_DIR 2>/dev/null || echo ~/.cache)/tmux-webui"

# 3. (optional) Remove Homebrew tap
brew untap operonlab/tap
```
