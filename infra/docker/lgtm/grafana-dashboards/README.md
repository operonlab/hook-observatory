# Grafana Dashboards — Workshop Debug

Drop dashboard JSON files here. Grafana provisioning is **not** auto-enabled for
the otel-lgtm bundled instance — import them manually via Grafana UI:

```
http://127.0.0.1:3100 → Dashboards → Import → upload .json
```

## Recommended dashboards to build

### 1. workshop-debug (main)

Variables:
- `$service` — dropdown from `label_values({job="workshop"}, service)`
- `$level` — multi-select: INFO/WARNING/ERROR/CRITICAL
- `$language` — derived label or hardcoded {python|rust|go|typescript}

Panels:

| Panel | Query | Visualization |
|---|---|---|
| Top errors by service (1h) | `sum by (service) (count_over_time({job="workshop"} \| json \| level="ERROR" [1h]))` | bar chart |
| Slowest routes p99 (5m windows) | `quantile_over_time(0.99, {service="core"} \| json \| unwrap duration_ms [5m])` | timeseries |
| Request timeline by request_id | `{job="workshop"} \| json \| request_id="$rid"` | logs |
| 5xx rate over time | `sum(count_over_time({service=~"$service"} \| json \| status_code >= 500 [5m]))` | timeseries |
| By-language error counts | `sum by (service) (count_over_time({job="workshop"} \| json \| level="ERROR" [1h]))` (post-process colour by language) | pie |
| Recent client errors | `{job="workshop-client-errors"}` | logs |

### 2. workshop-perf (optional)

Latency distribution per route, throughput, queue depth (if applicable).

## How to export your hand-built dashboard

Once you've built one in the UI:
- Dashboard settings → JSON Model → copy
- Save as `infra/docker/lgtm/grafana-dashboards/workshop-debug.json`
- Commit it — future Grafana provisioning can auto-load from this folder
