---
doc_version: 1
status: living-document
last_updated: 2026-05-12
---

# 重寫遷移狀態（Rewrite Migration Status）

這是一份**動態快照**，記錄 workshop 內各 service 的語言重寫進度與開源發行版同步狀態。
規範本身（命名、退場、發行）在 [folder-structure.md](./folder-structure.md)，本文檔只記錄「現在誰是事實源」。

## 命名與生命週期規則（三條鐵律）

1. **新建即正名** — 純新 Rust/Go 專案不掛後綴，直接用最終名（如 `rlm`、`agent-vista`、`hook-dispatcher`）
2. **重寫掛後綴** — 只在「同名 Python 還活著」期間掛 `-rs` / `-go`，視覺標記「過渡期、有債」
3. **接管即去綴** — 新版成為事實源時，舊版進 `_archive/`，新版去後綴繼承原名

衍生規則：
- `_archive/` 是 stations / libs 的標準退場區，README 記載 who/when/replaced_by/commit_hash
- 後綴出現在 path 即代表「未完成接管」— `grep -r '\-rs/\|\-go/' stations/` 可掃 waitlist
- 開源發行版採 **上游/下游 Distribution Pattern** — workshop 是事實源，發行版用 `git subtree split` 機械同步

## 狀態定義

| 狀態 | 含義 | 下一步 |
|------|------|--------|
| `experimental` | 新版開發中，Python 仍是 production | 跑 feature parity check |
| `parallel` | 新舊並行，各自有 caller | 排接管時程，或宣告為長期共存（reference impl） |
| `cutover` | 新版已切換為主，舊版待封存 | 執行接管流程（去綴 + archive） |
| `archived` | 舊版已封存，新版去綴繼承原名 | — |
| `solo` | 純新建，無前身 | — |

**特例：雙版本長期共存**

部分 service 採「Rust binary + Python reference impl + 雙 repo 開源」策略（如 session-channel），不走接管去綴流程。這類 service 在表中保留 `parallel` 狀態，並在備註欄明寫共存原因與兩邊 caller 分工。判準：Python 版是否仍有獨立 caller 群（CLI / 排程 / 開源使用者）。

## Rust 重寫狀態

| Service | 舊版位置 | 新版位置 | 狀態 | 備註 |
|---------|---------|---------|------|------|
| session-channel | `stations/session-channel/` | `stations/session-channel-rs/` | `parallel` | **長期雙版本並存**：Rust 接管主 service binary；Python 版定位為 reference impl + 開源發行版（`operonlab/session-channel` v0.2）。周邊 supervisor/CLI/wrappers/migrate 仍走 Python。Rust 版預計 6+ 月後另出開源 repo `operonlab/session-channel-rs`。詳見 `handoff/HANDOFF-20260512-1022-session-channel-phase8-opensource.md` |
| sentinel | `stations/_archive/sentinel-py/` | `stations/sentinel/` | `archived` | **2026-05-12 完成接管去綴**（commit `8242b49b`）。Python 版進 _archive；Rust 去綴繼承原名；workshop-launcher daemon spawn 新 binary `/release/sentinel`（PID 75499 live）；ws-sentinel-check disabled job 自 manifest 移除。Hardcode URL codegen 改造（commit `1fcdb897`）+ 3 regression test 也都同步繼承 |
| system-monitor | `stations/_archive/system-monitor-py/` | `stations/system-monitor/` | `archived` | **2026-05-12 完成接管去綴**（commit `c4dec64f`）。Python 版進 _archive；Rust 去綴繼承原名；workshop-launcher daemon 跑新 binary `/release/system-monitor`（PID 39394 live）；ws-sysmon-{weekly,monthly} disabled job 自 manifest 移除。Hardcode codegen 改造（commit `ee6082b5`）繼承 |
| agent-metrics | `stations/_archive/agent-metrics-py/` | `stations/agent-metrics/` | `archived` | **2026-05-12 完成接管去綴**。Python 進 _archive；Rust 去綴；workshop-launcher daemon 跑新 binary `/release/agent-metrics`（PID 23455 live, `/health` 回 `{"service":"agent-metrics"}`）。提前接管（Python 保留期至 2026-05-20，commented rollback entry 至該日清）。Hardcode codegen + quota_writer fix 繼承 |
| auto-survey | `stations/auto-survey/`（2026-04-19 已撤）| `stations/auto-survey/` | `archived` | **首例「接管即去綴」執行完成（2026-05-12, commit `be81bd55` + `73832f7f`）**：Cargo bin/lib name 去綴、workshop_services.py / .env / plist 三處 path 同步、新 binary `/release/auto-survey` 已產 (8.3MB)。`workshop_services.py` 內 commented Python entry 待 2026-05-19 保留期屆滿後清。waiting on 少爺執行 `launchctl unload + load` 完成 plist 重註冊 |
| remote-node | `stations/_archive/remote-node-py/` | `stations/remote-node/` | `archived` | **2026-05-12 完成接管去綴**。Python 進 _archive；Rust 去綴；workshop-launcher daemon spawn 新 binary `/release/remote-node`（PID 12711 live, `/health` 回 200）。順手清 `scripts/workshop_orphan_reaper.py` 內 protected_substrings。`agent-metrics-rs` 內 2 處歷史考古 comment（提到「10209 was a transient remote-node-rs shadow port」）保留 |
| ccusage | — | `stations/ccusage/` | `solo` | 2026-05-12 去綴；新 binary `~/.local/bin/ccusage` 已 cargo install（舊 `ccusage-rs` 已刪）；agent-metrics-rs 內 `CCUSAGE_BIN` path 同步更新 |
| rlm | — | `stations/rlm/` | `solo` | 已正名，無後綴 |
| port-registry | `libs/sdk-client/.../port_registry.py` | `libs/port-registry/` | `parallel` | 2026-05-12 去綴；Python (sdk-client 內) 與 Rust crate 並列 |
| sqlite-pool | — | `libs/sqlite-pool/` | `solo` | 2026-05-12 去綴；純 Rust 無 Python 前身 |
| desktop-assistant | — | `apps/desktop-assistant/src-tauri/` | `solo` | Tauri 內嵌 |
| mycelia | — | `lab/mycelia/` | `solo` | Workspace（8 crates）；lab/ 內為 POC，不適用 stations 規則 |

## Go 重寫狀態

| Service | 舊版位置 | 新版位置 | 狀態 | 備註 |
|---------|---------|---------|------|------|
| hook-dispatcher | `voice_notify.py`（已封存）| `stations/hook-dispatcher/` | `archived` | 已完成接管，無後綴；2026-05-12 13 處 hardcode URL 全改 `libs/go-port-registry` codegen，附帶修復 memvault.go 把 10205(translate) 改成 core 10000 |
| tmux-webui | `stations/_archive/tmux-webui-py/` | `stations/tmux-webui/` | `archived` | **2026-05-12 完成接管去綴**。Python `server.py` 進 _archive；Go 去綴；workshop_services.py workdir 同步；manifest 內舊 tmux-webui job 移除（multi-daemon entry 重複，workshop-launcher 已管）。Live binary `~/.local/bin/tmux-webui` (PID 33103, port 10105, `/` 回 200) |
| agent-vista | — | `stations/agent-vista/` | `solo` | 純新建 |
| lazy-wrapper | — | `mcp/lazy-wrapper/` | `solo` | 純新建 |

## Go Codegen 工具（2026-05-12）

`libs/go-port-registry/`（commit `9246a661`）— Go 端 ports.yaml codegen，與 Rust 的 `libs/port-registry/` 並列。`cmd/gen` subcommand 讀 yaml 生成 `ports.go` const 表。`yaml header` 已去除 "v2 planned"。新 Go service 進入 workshop 時 import 此 crate即可。

## 開源發行版（Distribution）狀態

採 **上游 / 下游** 心智：workshop 為事實源，發行版 = upstream + adapter shim + standalone deploy。完整規範見 [distribution-pattern.md](./distribution-pattern.md)。

| 內部位置（上游 / 事實源） | 開源 repo（下游 / 發行版） | 同步機制 | 狀態 | 備註 |
|--------------------------|---------------------------|---------|------|------|
| `stations/hook-observatory/` | `operonlab/hook-observatory` | `git subtree split` | `released` | 已驗證 pattern（[operonlab-release.md](../../.claude/rules/operonlab-release.md)） |
| `stations/session-channel/` | `operonlab/session-channel` | 規劃中（Phase 8）| `pre-release` | v0.2 即將開源，Python 版作為發行 base；Rust 版（`-rs`）未來另出 repo |
| `core/src/modules/memvault/` | `joneshong/memvault-os` | `docs/architecture/memvault-os-templates/scripts/sync-from-workshop.sh` | `templates-ready` | 2026-05-12 adapter shim 模板落地（auth_standalone + eventbus_inmem + docker-compose + bootstrap.sql + .env.example + sync script），少爺自己仍用 workshop 內 memvault，外人用下游發行版 |

下游 repo 共通結構（含 adapter shim 三件）已抽到 [distribution-pattern.md](./distribution-pattern.md)，這裡不重複。

少爺自己**不使用任何下游發行版** — 內部一律用 workshop 內版本，避免基礎設施雙開銷（這是少爺先前識別出的反模式）。

## 接管流程（cutover → archived 標準操作）

```
1. Feature parity check（新版功能 ≥ 舊版）
2. 切換所有 caller：
   - scripts/workshop_services.py
   - launchctl plist
   - infra/nginx workshop-apps.inc
   - libs/sdk-client/.../port_registry.py（若有）
3. 跑一輪完整 sentinel + 手動 smoke test
4. git mv stations/<name>/ stations/_archive/<name>-py/   ← 第一個 commit：純移動
5. git mv stations/<name>-rs/ stations/<name>/           ← 第二個 commit：去綴繼承
6. grep 全 repo 把 import / path / config 引用全部更新   ← 第三個 commit：清引用
7. 在 stations/_archive/README.md 記一行
8. 更新本文件（rewrite-status.md）
```

關鍵：步驟 4-5-6 拆三個 commit，revert 時只動 path、不動邏輯。

## Waitlist（按建議優先順序）

1. ~~**P0** — libs 命名校準~~ ✅ 2026-05-12 完成（直接去綴 `libs/port-registry/`、`libs/sqlite-pool/`）
2. ~~**P2** — session-channel 接管~~ ❌ 2026-05-12 評估後取消（Python 版定位為 reference impl + 開源發行版，雙版本長期並存）
3. ~~**P3** — hardcode URL 透過 `shared/ports.yaml` codegen 消除~~ ✅ 2026-05-12 全部完成
   - ✅ sentinel-rs（commit `1fcdb897`）
   - ✅ agent-metrics-rs（並行 agent commit `ee6082b5` + `6c69724a`）
   - ✅ system-monitor-rs（commit `ee6082b5`）
   - ✅ hook-dispatcher-go（並行 agent commit `9246a661` + `2de9f795`）
6. ~~**P6** — port 10209 (legacy fleet) 釐清~~ ✅ 2026-05-12（commit `6c69724a`，考古發現 10209 是 remote-node-rs 觀察期臨時 port，fleet 真實 port 10106，改用 yaml_url("fleet",...)）
7. ~~**P7** — Go codegen 工具 `libs/go-port-registry/`~~ ✅ 2026-05-12（commit `9246a661`，含 9 個 round-trip test；yaml header 已去除 "v2 planned" 標記）
8. **P5** — 首例 cutover 候選評估 ✅ 2026-05-12 完成（commit `e50f149a`，報告 `docs/architecture/cutover-candidates.md`，推薦首例 **auto-survey**：Python entry 已 retired 2026-04-19，保留期 2026-05-19 將屆滿）
9. ~~**P8** — 執行 auto-survey 接管~~ ✅ 2026-05-12（首例完成）
   - commit `be81bd55` git mv 純 rename
   - commit `73832f7f` Cargo metadata + caller refs 同步
   - **少爺需手動**：`launchctl unload ~/Library/LaunchAgents/com.workshop.auto-survey-rs.plist && launchctl load ~/Library/LaunchAgents/com.workshop.auto-survey-rs.plist`（plist 內 path 已 live update，重註冊後新 binary `auto-survey` 生效）
   - **保留期屆滿後（2026-05-19）**：清 `scripts/workshop_services.py:236-247` commented Python entry 與 `~/Library/LaunchAgents/*.disabled-2026-05-04`
   - **規範完備**：`stations/_archive/README.md` 首例範例已立
4. **P4** — Distribution Pattern 規格化（hook-observatory 已用 + session-channel 規劃 + memvault-os 規劃）→ 寫成共用文檔
5. **P5** — 首例 cutover 候選重評估：尋找真正「Python 已無 caller」的 service。從 `parallel` 狀態名單中挑（auto-survey-rs?、tmux-webui-go?）

## 引用

- 命名規範總述：[folder-structure.md](./folder-structure.md)
- Subtree split pattern：[operonlab-release.md](../../.claude/rules/operonlab-release.md)
- 多機部署架構：[multi-machine-architecture.md](./multi-machine-architecture.md)
