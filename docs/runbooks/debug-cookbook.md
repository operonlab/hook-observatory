# Debug Cookbook — 30 條找錯食譜

少爺 / Claude Code 找 workshop 任何 incident 的根據地。每個 service 的 log 都在
`/opt/homebrew/var/log/workshop/<service>/general.log`（JSON Lines，schema 見
`schemas/log-event.schema.json`）。

對應原則：
- 一個 `request_id` 串完前端 → core → MCP → station
- `level=ERROR` + `traceback` 是首選錨點
- `duration_ms` 拉慢 request
- `user_id` / `space_id` 圈使用者 / 工作空間

---

## 1. 找今天所有 500 / 5xx error

```bash
cat /opt/homebrew/var/log/workshop/core/general.log \
  | jq -c 'select(.status_code != null and .status_code >= 500)'
```

## 2. 過去 1 小時的 ERROR + 集中在哪個 service

```bash
date -v-1H +"%Y-%m-%dT%H:%M:%S" | read SINCE
for f in /opt/homebrew/var/log/workshop/*/general.log; do
  jq -r "select(.ts >= \"$SINCE\" and .level == \"ERROR\") | .service" "$f" 2>/dev/null
done | sort | uniq -c | sort -rn
```

## 3. 找某 user 過去 24h 的所有動作

```bash
USER_ID="01abc...your_user_id"
for f in /opt/homebrew/var/log/workshop/*/general.log; do
  jq -c "select(.user_id == \"$USER_ID\")" "$f" 2>/dev/null
done | sort -t'"' -k4
```

## 4. 跨服務追一個 request_id（最常用）

```bash
RID="testreq01"     # 從 browser DevTools / response header / 上游 log 抓
grep -l "\"request_id\":\"$RID\"" /opt/homebrew/var/log/workshop/*/general.log \
  /opt/homebrew/var/log/workshop/mcp-*/server.log 2>/dev/null

# 然後合併排序看時間軸
for f in $(grep -l "\"request_id\":\"$RID\"" /opt/homebrew/var/log/workshop/*/*.log 2>/dev/null); do
  grep "\"request_id\":\"$RID\"" "$f" | jq -c "{ts, service, level, msg, status_code, duration_ms}"
done | jq -s 'sort_by(.ts)'
```

## 5. 找最慢的 10 個 request

```bash
cat /opt/homebrew/var/log/workshop/core/general.log \
  | jq -c 'select(.duration_ms != null)' \
  | jq -s 'sort_by(-.duration_ms) | .[0:10] | .[] | {ts, path, method, duration_ms, status_code, request_id}'
```

## 6. 某個 MCP server 過去一天的所有 exception

```bash
SERVICE=mcp-finance
jq -c 'select(.level == "ERROR" and .traceback != null)' \
  /opt/homebrew/var/log/workshop/$SERVICE/server.log
```

## 7. workbench frontend 錯誤上報（client-error）

```bash
cat /opt/homebrew/var/log/workshop/core/client-errors.log \
  | jq -c '{ts, client_message, client_url, client_request_id}'
```

## 8. Rust station 啟動 panic / fatal

```bash
# Rust workshop-log 也寫 general.log 同 schema
SERVICE=sentinel
jq -c 'select(.level == "ERROR" or .msg | contains("panic"))' \
  /opt/homebrew/var/log/workshop/$SERVICE/general.log
```

## 9. Go station hook-dispatcher 任一 handler 失敗

```bash
jq -c 'select(.level == "ERROR")' \
  /opt/homebrew/var/log/workshop/hook-dispatcher/general.log
```

## 10. 看 admin 角色變更 audit

```bash
# admin-audit.log 是 P2 admin audit middleware 分流出的隔離檔
jq -c 'select(.action != null)' \
  /opt/homebrew/var/log/workshop/core/admin-audit.log
```

## 11. tail -f 多個 service 同時

```bash
SERVICES="core sentinel hook-dispatcher mcp-finance"
for s in $SERVICES; do
  tail -f /opt/homebrew/var/log/workshop/$s/*.log &
done
# Ctrl+C 一次只結束 foreground，要 `kill %1 %2 %3...` 全砍
```

## 12. 找今天 status_code 4xx 但非 401/403 的可疑請求

```bash
jq -c 'select(.status_code != null and .status_code >= 400 and .status_code < 500 and .status_code != 401 and .status_code != 403)' \
  /opt/homebrew/var/log/workshop/core/general.log
```

## 13. 用 ajv 驗證所有 log 行符合 schema

```bash
# 需 npm i -g ajv-cli
jq -c . /opt/homebrew/var/log/workshop/core/general.log | head -100 | while read line; do
  echo "$line" | ajv validate -s schemas/log-event.schema.json -d /dev/stdin || echo "FAIL: $line"
done
```

## 14. 找 capture-console websocket 斷線

```bash
jq -c 'select(.msg | test("websocket|WebSocket|disconnect"; "i"))' \
  /opt/homebrew/var/log/workshop/capture-console/general.log
```

## 15. 找 ocr / stt / tts / vision 引擎載入失敗

```bash
for s in ocr stt tts vision; do
  echo "=== $s ==="
  jq -c 'select(.level == "ERROR" and (.msg | test("engine|model|load"; "i")))' \
    /opt/homebrew/var/log/workshop/$s/general.log 2>/dev/null | head -5
done
```

---

## 給 Claude Code 用的 Read recipe

當你 (Claude Code) 在 debug 一個 incident 時，先 Read 這幾個檔案會比 grep 快：

```
Read /opt/homebrew/var/log/workshop/core/general.log limit=200
```
看最近 200 行（自動倒序，剛剛發生的事在前）。每行是合法 JSON，可以直接抽 `level=ERROR` / `request_id` / `duration_ms`。

連同抓到的 request_id：
```
Bash: grep "01abc..." /opt/homebrew/var/log/workshop/*/general.log /opt/homebrew/var/log/workshop/mcp-*/server.log
```
找跨服務串接。再 Read 命中的 service log 上下文 ±20 行。

---

## P3 LGTM LogQL recipe（Grafana Loki）

P3 啟用 Loki + Promtail 後，這些 query 直接在 Grafana Explore 用：

| 目的 | LogQL |
|---|---|
| 某 service 全部 error | `{service="mcp-finance"} \|= "level\":\"ERROR\""` |
| 跨服務串 request_id | `{job="workshop"} \| json \| request_id="01abc..."` |
| 某 user 行為 | `{job="workshop"} \| json \| user_id="01abc..."` |
| p99 慢 route | `quantile_over_time(0.99, {service="core"} \| json \| unwrap duration_ms [5m])` |
| by-language 切視角 | `sum by (service) (count_over_time({job="workshop"} \| json \| level="ERROR" [1h]))` |

---

## 常見 incident 與起點

| 症狀 | 起點 log | 關鍵欄位 |
|---|---|---|
| 前端按鈕點不動 | `core/client-errors.log` | `client_message`, `client_url` |
| 某 API 500 | `core/general.log` `level=ERROR` | `traceback`, `path`, `request_id` |
| MCP tool 回 `[error] ...` | `mcp-{name}/server.log` | `traceback`, `error_type` |
| Rust station 啟動失敗 | `{station}/general.log` | `level=ERROR` 第一筆 |
| Go hook 沒觸發 | `hook-dispatcher/general.log` | `msg`, `request_id` |
| 服務沒啟動 | launchd 的 `*.error.log`（不是 schema 內，但 fallback）| stderr text |
| Cronicle job 失敗 | Cronicle UI / `scheduler/general.log` | `msg`, `level` |

---

## 起源 request_id 怎麼來

- **Browser**: `crypto.randomUUID().slice(0,12)` 由 `workbench/src/api/client.ts` 自動產生並送 `X-Request-ID` header
- **Core**: `core/src/middleware/request_id.py` 收到 header 套用；若無則生新 id
- **Outgoing HTTP from Core**: `libs/sdk-client/sdk_client/sdk_base.py` 自動把 ContextVar 的 id 放 header 給 downstream
- **Rust station axum**: `workshop_log::middleware::RequestIdLayer` 從 header 抽出塞 `tracing::Span`
- **Go station net/http**: `workshoplog.RequestIDMiddleware` 從 header 抽出塞 `context.Context`
- **MCP server**: 走 stdio 沒有 header — `_format_error()` 仍會 log 但 request_id 可能為空（後續可從 mcpproxy 傳遞）

## CLI 起源

CLI 工具（用 `init_cli_logging("name")`）每次跑會自動產生 12-hex `WORKSHOP_REQUEST_ID`，後續 SDK call 帶在 header 上。手動指定：
```bash
WORKSHOP_REQUEST_ID=01myreqid01 workshop fleet dispatch ...
```
