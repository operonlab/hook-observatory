# hook-observatory (Python) — full archive

整個 `stations/hook-observatory/` Python source tree 在 2026-05-13 歸檔，hook 執行路徑由 Go binary `hook-dispatcher` 接管。

## 取代

| Python (this archive) | Go replacement (live) |
|---|---|
| 36 個 `handlers/*.py` handler | `stations/hook-dispatcher/internal/handlers/*.go` (Stage 3 parity baseline) |
| `main.py` / `auth.py` / `routes.py` / `schemas.py` / `database.py` / `store.py` / `spool.py` — FastAPI dashboard | 被 `stations/session-channel/` dashboard 取代（commit `ef3264fc` 已清 pane 殘留） |
| `install.py` — Homebrew installer | `stations/hook-dispatcher/install.sh`（Bash + jq，輕量；commit `4cff3222`） |
| `voice_notify_runner.py` — Go panic fallback | 不再需要（Go binary panic 時 fallback 到 macOS `say`） |
| `handlers/tool_registry.json` | `stations/hook-dispatcher/assets/tool_registry.json`（commit `4296d75e`） |
| `config.example.yaml` | `stations/hook-dispatcher/config.example.yaml`（commit `4296d75e`） |
| `config.yaml`（local override，.gitignore'd） | `stations/hook-dispatcher/config.yaml`（少爺手動 mv 本機 local） |
| `installer/` — Tauri installer wizard | （未取代，OSS user 用 Homebrew formula + install.sh） |
| `cli/` — CLI wrappers | （未取代，相關 CLI 已由 `channel` / `session-channel` 取代） |
| `frontend/` — React dashboard | （未取代，session-channel dashboard 取代） |

## Cutover 時間線

| 日期 | 事件 |
|---|---|
| 2026-04-04 | `operonlab/hook-observatory` Python repo 最後一次 push |
| 2026-05-06 | hook 執行路徑全面切到 Go binary `~/.claude/hooks/hook-dispatcher`；Python handlers 不再被觸發 |
| 2026-05-12 | session-channel dashboard 取代 hook-observatory dashboard 大部分功能（commit `ef3264fc`） |
| 2026-05-13 | 完整 cutover：context_supervisor.py 拍板放棄；handler/dashboard/installer Python source 整批歸檔 |

## Parity 驗證

2026-05-13 Phase A.3 前置 audit 派獨立 reviewer 對 32 個同名 handler 做結構性 parity check，結果：

- **Tier 1**（24 個）— Python event subscription = Go event subscription = matcher 一致 = 方向同。安全歸檔。
- **Tier 2**（5 個：`session_channel` / `session_namer` / `anvil_telemetry` / `sentinel_notify` / `pm_autopilot`）— Go 端擴充或執行順序差異，功能不會丟失。安全歸檔。
- **Tier 3**（3 個：`annotate_insight_hook` / `issue_sync` / `read_edit_ratio`）— 兩邊皆 `// Not registered`，是有意預留的 opt-in 槽位（**不是** silently dead）。安全歸檔。

換言之：**沒有任何 Python handler 處於「自以為在跑但 Go 沒接管」的 silently dead 狀態**。

## 例外：`handlers/context_supervisor.py`（功能放棄）

`context_supervisor.py` (1002 行) 三層 context 健康監控（Layer 1 pressure / Layer 2 heuristic drift / Layer 3 LLM + embedding coherence）訂閱 5 events（SessionStart, PostToolUse, Stop, UserPromptSubmit, PreCompact），是**少數**沒有被 Go binary 接管的 handler。

事實上：
- Go 端的 `context_relay.go + context_inject.go` 名字撞名但職責完全不同（session 接續 + sub-agent context 注入），**沒接管**監控邏輯
- Python 端 `handlers/__init__.py` REGISTRY 內早就用 `# context_supervisor: disabled — concept good, scoring inaccurate` 註解停用所有路由
- 三層監控功能因此自 2026-05-06 silently 停運 6+ 天直到 2026-05-13 audit 才被發現

少爺 2026-05-13 拍板「不要這個功能」（concept good, scoring inaccurate）— 不重寫進 Go、不 shell-out。

`context_supervisor.py` 已於 commit `b609c54f` 先一步從 `stations/hook-observatory/handlers/` 搬到 `stations/_archive/hook-observatory-handlers-py/`；本次 full archive 時合併進 `stations/_archive/hook-observatory-py/handlers/context_supervisor.py`，舊 `hook-observatory-handlers-py/` 目錄已 rmdir。同 commit 一併清掉 `handlers/__init__.py` 內 `_try_import` 入口與 6 處 disabled 註解。

## 規範

- 此目錄符合 `stations/_archive/README.md` 規範：「不被 build / lint / test 流程觸碰，純歷史」
- 命名：`hook-observatory-py/`（符合 `<original-name>-<lang>/` 慣例）
- 對應 Go 取代位置：`stations/hook-dispatcher/`
- 對應 OSS repo（Phase B 後）：`operonlab/hook-observatory`（Python source 將被 Go binary 覆蓋）

## Rollback

若需把 Python source 撈回主目錄樹：

```bash
git mv stations/_archive/hook-observatory-py stations/hook-observatory
# 並回退 Phase A.1-A.5 對應的 Go 路徑改動 + port_registry 清理 + multi-CLI doc 清理
```

git history 完整保留，所有 rename 用 `git mv` 不會破壞 blame。
