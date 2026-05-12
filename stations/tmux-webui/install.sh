#!/bin/sh
# tmux-webui installer — single-binary, curl-pipe friendly.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/operonlab/tmux-webui/main/install.sh | sh
#
# Detects OS+arch, fetches the latest GitHub release tarball, verifies
# the checksum, and drops the binary in $HOME/.local/bin (or /usr/local/bin
# if writable).

set -eu

REPO="operonlab/tmux-webui"
BIN="tmux-webui"

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
case "$OS" in
  darwin|linux) : ;;
  *) echo "tmux-webui: unsupported OS '$OS' (need darwin or linux)"; exit 1 ;;
esac

ARCH=$(uname -m)
case "$ARCH" in
  x86_64|amd64) ARCH=amd64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *) echo "tmux-webui: unsupported arch '$ARCH'"; exit 1 ;;
esac

# Latest tag from GitHub API.
VERSION=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
  | grep '"tag_name"' | head -1 | cut -d'"' -f4)
if [ -z "${VERSION:-}" ]; then
  echo "tmux-webui: could not resolve latest release"
  exit 1
fi

TARBALL="${BIN}_${VERSION#v}_${OS}_${ARCH}.tar.gz"
URL="https://github.com/$REPO/releases/download/$VERSION/$TARBALL"
SUMURL="https://github.com/$REPO/releases/download/$VERSION/${BIN}_${VERSION#v}_checksums.txt"

TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

echo "tmux-webui: downloading $TARBALL ($URL)"
curl -fsSL "$URL" -o "$TMP/$TARBALL"

echo "tmux-webui: verifying checksum"
curl -fsSL "$SUMURL" -o "$TMP/checksums.txt"
if command -v shasum >/dev/null 2>&1; then
  (cd "$TMP" && shasum -a 256 -c --ignore-missing checksums.txt 2>/dev/null \
    | grep "$TARBALL" >/dev/null) \
    || { echo "tmux-webui: checksum mismatch"; exit 1; }
elif command -v sha256sum >/dev/null 2>&1; then
  (cd "$TMP" && sha256sum -c --ignore-missing checksums.txt 2>/dev/null \
    | grep "$TARBALL" >/dev/null) \
    || { echo "tmux-webui: checksum mismatch"; exit 1; }
else
  echo "tmux-webui: warning — no shasum/sha256sum, skipping verification"
fi

tar -xzf "$TMP/$TARBALL" -C "$TMP"

if [ -w /usr/local/bin ]; then
  DEST=/usr/local/bin
else
  DEST="$HOME/.local/bin"
  mkdir -p "$DEST"
fi

mv "$TMP/$BIN" "$DEST/$BIN"
chmod +x "$DEST/$BIN"

echo
echo "tmux-webui: installed to $DEST/$BIN"

case ":$PATH:" in
  *":$DEST:"*) : ;;
  *) echo "tmux-webui: add $DEST to PATH:  export PATH=\"$DEST:\$PATH\"" ;;
esac

if ! command -v tmux >/dev/null 2>&1; then
  cat <<EOF

tmux-webui needs tmux installed. Install it via:
  brew install tmux           (macOS)
  sudo apt install tmux       (Debian/Ubuntu)
  sudo pacman -S tmux         (Arch)

EOF
fi

echo "Run:  $BIN"
echo "Then: open http://localhost:9527"
