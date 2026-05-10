# Build from source

## Prerequisites

- Go 1.24+ (`go version`)
- tmux (`brew install tmux` / `sudo apt install tmux`)
- git

## Clone & build

```sh
git clone https://github.com/operonlab/tmux-webui
cd tmux-webui
go build -o tmux-webui ./cmd/tmux-webui
./tmux-webui --version
```

The build embeds all frontend assets via `go:embed`, so the resulting binary is self-contained.

## Install for the current user

```sh
go install github.com/operonlab/tmux-webui/cmd/tmux-webui@latest
```

This drops the binary in `$GOBIN` (defaults to `$HOME/go/bin`).

## With version stamping (matches release binaries)

```sh
VERSION=$(git describe --tags --always)
GIT_HASH=$(git rev-parse --short HEAD)
BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)

go build -trimpath \
  -ldflags "-s -w \
    -X github.com/operonlab/tmux-webui/internal/buildinfo.Version=$VERSION \
    -X github.com/operonlab/tmux-webui/internal/buildinfo.GitHash=$GIT_HASH \
    -X github.com/operonlab/tmux-webui/internal/buildinfo.BuildDate=$BUILD_DATE" \
  -o tmux-webui ./cmd/tmux-webui
```

## Cross-compile

`CGO_ENABLED=0` is the default for releases; the binary is statically linked.

```sh
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o tmux-webui-linux-arm64 ./cmd/tmux-webui
GOOS=darwin GOARCH=amd64 CGO_ENABLED=0 go build -o tmux-webui-darwin-amd64 ./cmd/tmux-webui
```

## Run tests

```sh
go test ./...                                       # unit
go test -race ./internal/ws/ ./internal/tts/        # race detector
go test -tags=tmux_integration ./internal/tmuxctl   # against real tmux server
```

## Local goreleaser snapshot (no GitHub publish)

```sh
goreleaser release --snapshot --clean
ls dist/
```
