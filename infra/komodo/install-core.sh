#!/bin/bash
# Install Komodo Core on Mac
# Komodo Core = central control plane (web UI + API)
# Docs: https://komo.do/docs/server-management/install
set -e

KOMODO_PASSKEY="${KOMODO_PASSKEY:-workshop-fleet-2026}"
KOMODO_PORT="${KOMODO_PORT:-9120}"

echo "Installing Komodo Core..."
docker pull ghcr.io/moghtech/komodo-core:latest

docker run -d \
  --name komodo-core \
  --restart unless-stopped \
  -p "${KOMODO_PORT}:9120" \
  -v komodo-data:/data \
  -e KOMODO_PASSKEY="${KOMODO_PASSKEY}" \
  ghcr.io/moghtech/komodo-core:latest

echo "Komodo Core running at http://localhost:${KOMODO_PORT}"
echo "Next: register Periphery agent from Windows WSL2 with passkey: ${KOMODO_PASSKEY}"
