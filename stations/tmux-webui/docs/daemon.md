# Run tmux-webui as a service

`tmux-webui daemon` writes a platform-native unit file and (optionally) loads it. Once installed, your server keeps running across reboots.

## Install

```sh
tmux-webui daemon install
```

What this does:

- **macOS**: writes `~/Library/LaunchAgents/dev.tmux-webui.plist` and runs `launchctl bootstrap gui/$(id -u) <plist>`.
- **Linux**: writes `~/.config/systemd/user/tmux-webui.service` and runs `systemctl --user daemon-reload && systemctl --user enable --now tmux-webui`.

> On Linux, also run `sudo loginctl enable-linger $USER` if you want the service to keep running after you log out (without a session).

Pass `--dry-run` to print the unit file without invoking launchctl/systemctl — useful for inspection or sandboxed environments.

## Inspect

```sh
tmux-webui daemon status
tmux-webui daemon logs        # tails platform log
```

## Uninstall

```sh
tmux-webui daemon uninstall
```

Removes the unit file and unloads it.

## Why not just `nohup`?

- launchd / systemd restart on crash (`KeepAlive=true` / `Restart=on-failure`)
- Logs go to a real log destination (`~/.local/share/tmux-webui/{stdout,stderr}.log` on mac, `journalctl --user -u tmux-webui` on linux)
- Survives reboots without a login shell

## Alternative: run inside tmux

Ironic but valid. Open a window in your existing tmux session and run `tmux-webui`. Detach. The pane keeps the server alive as long as tmux runs.

```sh
tmux new-window -d -n webui 'tmux-webui'
```
