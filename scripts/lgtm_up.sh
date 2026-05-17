#!/usr/bin/env bash
# Start the observability stack (LGTM + Promtail) on demand.
# Default state is OFF — only run this when少爺 actually wants the Grafana UI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/infra/docker"

echo "[lgtm-up] starting observability profile (lgtm + promtail)..."
docker compose --profile observability up -d

echo "[lgtm-up] waiting for grafana healthcheck..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:3100/api/health > /dev/null; then
    echo "[lgtm-up] grafana healthy"
    break
  fi
  sleep 2
done

cat <<EOF

[lgtm-up] Stack is up.

  Grafana UI:   http://127.0.0.1:3100   (admin / admin)
  OTLP gRPC:    127.0.0.1:4317
  OTLP HTTP:    127.0.0.1:4318
  Promtail:     tails /opt/homebrew/var/log/workshop/*/*.log → lgtm

Quick LogQL tests in Grafana → Explore → Loki:

  {job="workshop"}                                # all workshop logs
  {service="core"} |= "level\":\"ERROR\""         # core errors
  {job="workshop"} | json | request_id="01abc..." # trace one request cross-service
  {job="workshop-client-errors"}                  # frontend errors

Stop:
  cd $ROOT/infra/docker && docker compose --profile observability down

EOF
