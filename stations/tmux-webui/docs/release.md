# Releasing tmux-webui

`v0.1.0` is the first public release. After that, every tag triggers an automated release pipeline.

## Pre-release checklist

- [ ] [Dogfooded](dogfood.md) for at least a week with no `revert` events.
- [ ] `go test ./...` passes locally.
- [ ] `go test -race ./internal/ws/ ./internal/tts/ ./internal/autocomplete/` passes.
- [ ] `go test -tags=tmux_integration ./internal/server` passes against a real tmux server.
- [ ] CHANGELOG.md updated with a section for the new version.
- [ ] README status table reflects reality.
- [ ] `docs/demo.gif` exists (record with [vhs](https://github.com/charmbracelet/vhs) or asciinema).
- [ ] Homebrew tap repo `operonlab/homebrew-tap` exists and is reachable.

## Cutting the release

Once the checklist is clean:

```sh
# 1. Sync your branch with main and ensure clean tree.
git checkout main
git pull
git status   # must be clean

# 2. Tag with the new version.
git tag -a v0.1.0 -m "v0.1.0 — first public release"
git push origin v0.1.0
```

The tag push triggers GoReleaser via GitHub Actions. The default workflow:

1. Cross-compiles for `darwin/{amd64,arm64}` and `linux/{amd64,arm64}`.
2. Strips symbols (`-s -w`), trims paths (`-trimpath`), and injects build info via `-ldflags`.
3. Packages into `tmux-webui_{version}_{os}_{arch}.tar.gz` archives with `LICENSE` and `README.md`.
4. Generates a `tmux-webui_{version}_checksums.txt` with SHA-256 sums.
5. Creates a GitHub Release (draft) with the changelog excerpt and uploads all artifacts.
6. Pushes a Homebrew formula update to `operonlab/homebrew-tap`.

See [`.goreleaser.yaml`](../.goreleaser.yaml) for the exact configuration.

## Local snapshot (no GitHub publish)

For verifying the build matrix before tagging:

```sh
goreleaser release --snapshot --clean
ls dist/
# tmux-webui_0.1.0-snapshot-XXXXXXX_darwin_arm64.tar.gz
# tmux-webui_0.1.0-snapshot-XXXXXXX_linux_amd64.tar.gz
# ...
# tmux-webui_0.1.0-snapshot-XXXXXXX_checksums.txt
```

Test one of the archives by extracting and running `--version`:

```sh
mkdir -p /tmp/tw-test && tar -xzf dist/tmux-webui_*_darwin_arm64.tar.gz -C /tmp/tw-test
/tmp/tw-test/tmux-webui version
```

The reported `git_hash` should match `git rev-parse --short HEAD`.

## Required GitHub secrets

For the GitHub Actions release workflow to succeed, the `operonlab/tmux-webui` repo needs:

| Secret | Purpose |
|--------|---------|
| `GITHUB_TOKEN` | Default — uploads release assets and creates the release. Auto-injected. |
| `HOMEBREW_TAP_GITHUB_TOKEN` | A PAT (`public_repo` scope) for `operonlab/homebrew-tap`. GoReleaser needs this to commit the formula update. |

Set the second one via:

```sh
gh secret set HOMEBREW_TAP_GITHUB_TOKEN --body "$(cat ~/.tap-pat)" --repo operonlab/tmux-webui
```

## Promoting from draft

GoReleaser leaves the release as a **draft** by default (per `.goreleaser.yaml: release.draft = true`). Review the rendered release notes on GitHub, then click "Publish release" to make it visible to users.

The `install.sh` looks at the *latest* release, so until you publish the draft, `curl | sh` still installs the previous version.

## Patch / minor releases

Same flow with the next semver tag:

```sh
git tag -a v0.1.1 -m "v0.1.1 — fix CJK pane wrap on iOS"
git push origin v0.1.1
```

CHANGELOG.md should grow a new section before tagging — GoReleaser will surface entries between tags in the release notes automatically (filtered via `.goreleaser.yaml: changelog.filters.exclude`).

## When things go wrong

- **Release workflow fails halfway** → delete the half-uploaded GitHub Release and the tag, fix, re-tag with the same version. (No one has installed it yet because the install script reads `releases/latest`, which only updates after publish.)
- **Homebrew formula push fails** → token expired or `operonlab/homebrew-tap` doesn't exist. The release still ships; users can `curl | sh` while you fix the tap.
- **Wrong checksum on GitHub** → almost certainly a manual edit. Don't manually edit release artifacts; re-tag and re-release.

## After the release

- Update README's status table from `🚧 first release pending` to `✅ v0.1.0`.
- Announce on whatever channels you use.
- Open issues for known limitations so users have a place to land bug reports instead of email.
