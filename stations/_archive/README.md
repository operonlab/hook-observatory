# Stations Archive

冷凍區。Station 在「接管即去綴」流程結束後，舊版（被取代的實作）搬進此目錄保留歷史，避免污染主目錄樹但保留 git history 與 rollback 可能。

## 規範

- 進入此目錄的內容**不被 build / lint / test 流程觸碰**，純歷史
- 命名：`<original-name>-<lang>/`，例如 `auto-survey-py/`、`sentinel-py/`
- 每次封存在下方表格記載一行

## 封存記錄

| 日期 | 原 station | 取代為 | 取代版本 commit | 原因 |
|------|-----------|-------|----------------|------|
| 2026-04-19 | `stations/auto-survey/` (Python) | `stations/auto-survey/` (Rust，由 `auto-survey-rs` rename) | `9d34...`（retired commit）/ `<本次 cutover commit>` | Rust binary 性能與部署簡便；Python source 早於 2026-04-19 已刪除，本 README 補登。實際 directory 未進入 `_archive/`（已撤），workshop_services.py 內留 commented entry 至 2026-05-19 過保留期後可清 |
| 2026-05-12 | `stations/sentinel/` (Python, → `sentinel-py/`) | `stations/sentinel/` (Rust，由 `sentinel-rs` rename) | `8242b49b` (cutover step 2) | Rust binary 已 production 跑數週，Python schedule job (`ws-sentinel-check`) 自 2026-05-01 enabled=false。本次直接 git mv 進 `_archive/` |
| 2026-05-12 | `stations/system-monitor/` (Python, → `system-monitor-py/`) | `stations/system-monitor/` (Rust，由 `system-monitor-rs` rename) | `c4dec64f` (cutover step 2) | Rust binary 已 production 跑數週（RSS 58MB→15MB），Python schedule jobs (`ws-sysmon-weekly` / `ws-sysmon-monthly`) 自 2026-05-01 enabled=false。本次 git mv 進 `_archive/` |
| 2026-05-12 | `stations/remote-node/` (Python, → `remote-node-py/`) | `stations/remote-node/` (Rust，由 `remote-node-rs` rename) | `1b87b39e` (cutover step 2) | HTTP proxy to Windows GPU；Rust binary 已 production；本次 git mv 進 `_archive/` |
| 2026-05-12 | `stations/agent-metrics/` (Python, → `agent-metrics-py/`) | `stations/agent-metrics/` (Rust，由 `agent-metrics-rs` rename) | (本次 cutover commit) | Python 自 2026-04-20 retired，提前接管（保留期至 2026-05-20）；Rust binary `/release/agent-metrics` live |

## 規則衍生

- 若舊版 source 在接管前**已從 main branch 移除**（例如 auto-survey），則本表仍記載「曾存在」的事實 + retired commit hash，方便日後考古 `git log --all --diff-filter=D --name-only -- stations/auto-survey/` 找回
- 若舊版 source 真實搬進來，目錄須附 `_DEPRECATED.md` 指明取代版本位置與 commit hash
