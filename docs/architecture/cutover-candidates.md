# Cutover Candidates (P5) — 2026-05-12

| Service | workshop_services.py 用哪版 | Python caller 證據 | 接管建議 |
|---------|---------------------------|-------------------|---------|
| auto-survey | **Rust binary** (`auto-survey-rs`) — Python entry 已整段 comment out，備註「retired 2026-04-19，30天後可刪（2026-05-19）」 | `workshop_services.py:241-246` 全在 comment 內，無 active caller | **可接管** |
| sentinel | **Rust binary** (`sentinel-rs`) — `workshop_services.py` 直接用 `sentinel-rs` binary，無 Python entry | `schedules/manifest.json:731` ws-sentinel-check 命令指向 Python venv，但 `enabled: false`，description 標明「已停用 2026-05-01」 | **可接管**（需同步清除已停用排程） |
| system-monitor | **Rust binary** (`system-monitor-rs`) — Python entry 已替換，rollback comment 保留於 `workshop_services.py:173` | `schedules/manifest.json:177,193` ws-sysmon-weekly / ws-sysmon-monthly 指向 Python `reporter.py`，但兩者 `enabled: false`，description 標明「已停用 2026-05-01」 | **可接管**（需同步清除已停用排程） |

## 首例推薦

**選擇**: `auto-survey`

**理由**: Python entry 在 `workshop_services.py` 已 comment out 超過 3 週（retired 2026-04-19），30天保留期（2026-05-19）即將屆滿，無任何 active caller，且沒有 sentinel/system-monitor 的殘留已停用排程需要一併清理，最乾淨。

## 接管 Checklist（以 auto-survey 為首例）

- [ ] 確認 `workshop_services.py` 中 Python 舊 entry comment 已過保留期（2026-05-19 後）
- [ ] 刪除 `workshop_services.py` 中 `# Python auto-survey retired` comment block（241-255 行）
- [ ] 確認 launchctl plist 無殘留 `auto-survey`（非 `auto-survey-rs`）plist
- [ ] 確認 infra/nginx 反代指向正確 port（port_registry 中 `auto-survey` port，兩版共用）
- [ ] `git mv stations/auto-survey/ stations/_archive/auto-survey-py/`
- [ ] `git mv stations/auto-survey-rs/ stations/auto-survey/`
- [ ] 更新 `stations/auto-survey/` 內部所有自我引用路徑（SKILL.md、Makefile、Dockerfile 等）
- [ ] `grep -rn "auto-survey-rs" scripts/ schedules/ infra/ docs/` 批次更新引用
- [ ] `grep -rn "auto-survey-rs" workbench/src/` 確認前端無直接引用
- [ ] 跑 auto-survey smoke test 確認服務仍綠（`curl http://127.0.0.1:<port>/health`）

## 後續候選（sentinel / system-monitor）

兩者 `workshop_services.py` 已切 Rust，但各有 1-2 個 `enabled: false` 排程仍指向 Python binary。
接管前應先將對應排程 command 改為 Rust 版本或移除，再執行 `git mv`。
