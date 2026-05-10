# `shared/` — Cross-Language Schema Single Source of Truth

> **不是 runtime lib。是 build-time spec + codegen。**
> 三語言（Python / Rust / Go）各自獨立運作，只共享規格。

## 為什麼存在

Workshop 從 Python 起家，逐步把若干 station 用 Rust/Go 重寫追求性能（sentinel-rs / agent-metrics-rs / system-monitor-rs / hook-dispatcher / agent-vista / auto-survey-rs / remote-node-rs）。重寫過程中，port 設定與 schema 在三語言之間靜默漂移：

- `stations/sentinel-rs/src/checker/registry.rs` 整檔內聯 38 條 hardcoded HTTP check，註解明示「mirroring Python (2026-04-18 snapshot)」，無同步機制
- 6 個 Rust/Go 專案合計 60+ 處 port hardcode

`shared/` 解決這件事：**規格層唯一真值源 + 三語言 codegen**。Python 端 runtime 載入 yaml，Rust/Go 端 build-time 從 yaml 生成 source。任何漂移在 CI 階段被 `scripts/check_schema_drift.py` 攔下。

## 哲學

| 做 | 不做 |
|----|------|
| 規格 single source of truth（port_registry, 未來 payload schema） | 跨語言 code 共用（logger, config loader, HTTP client） |
| Build-time codegen（cargo build / go generate 時生成 source） | Runtime FFI / dynamic loading |
| 漸進收斂（每次只動一個 station） | 大爆炸式 refactor |
| Drift CI gate 阻擋未來漂移 | 信任「人眼對齊」 |

## 目錄結構

```
shared/
├── README.md                         # 本檔
└── schemas/
    └── port_registry.yaml            # 唯一真值源（v1）
```

## Consumers

| 語言 | 機制 | 入口 |
|------|------|------|
| Python | Runtime 載入 | `libs/sdk-client/sdk_client/port_registry.py` |
| Rust | Build-time codegen | `libs/rust-port-registry/build.rs` → `OUT_DIR/ports.rs` |
| Go (v2) | `//go:generate` 預期 | (尚未實作) |

新 station 接入步驟：
1. **Rust**：`Cargo.toml` 加 `workshop-port-registry = { path = "../../libs/rust-port-registry" }`，程式碼用 `workshop_port_registry::{PORTS, get, by_group}`
2. **Python**：直接 `from sdk_client.port_registry import get_port, get_url`
3. **Go (v2)**：等 `libs/go-port-registry/` 落地

## Drift 守門員

`scripts/check_schema_drift.py --check` 掃 Rust/Go station source code，找 `127.0.0.1:PORT` / `localhost:PORT` 字面，比對 yaml：

- **UNKNOWN**：port 不在 yaml — 警告（可能是非 workshop 服務）
- **PASS**：port 在 yaml 內

**v1 限制（known）**：name-blind drift。port 對但服務名錯（例：`memvault.go` 用 10205 但 10205 是 translate）抓不到。完整 name-aware 守門員需要全 codegen，留 v2。

## v1 範圍 / 不做什麼

**做**：
- `schemas/port_registry.yaml`（37 個 service）
- Python runtime loader
- Rust shared crate `libs/rust-port-registry/`
- 試金石：`stations/sentinel-rs` 38 條 HTTP check 從 PORTS 動態組
- `scripts/check_schema_drift.py` + 接 sentinel light_check

**不做（v∞ 或 v2 follow-up）**：
- 抽 cross-language code（logger / config / HTTP client）
- FFI binding
- Go codegen（hook-dispatcher / agent-vista 改造留 v2）
- agent-metrics-rs / system-monitor-rs / auto-survey-rs hardcode 改造（v2 各 station 獨立 PR）
- payload schema（sysmon / service-tracker / memory-sync）— port 漂移最痛，payload 暫無實證痛點

## 變更流程

改 `port_registry.yaml`：

1. 編輯 yaml
2. Python：自動生效（next import）
3. Rust：`cargo build` 觸發 build.rs rerun（已設 `cargo:rerun-if-changed`）
4. CI：`scripts/check_schema_drift.py --check` 確認 Rust/Go station 沒有 stale hardcode

新增 service：
1. yaml 加新 entry
2. 若 service 該被 sentinel 監測，sentinel-rs `src/checker/registry.rs` 自動接收（HTTP check 從 PORTS 動態組）
3. 若需要特殊 health logic，在 sentinel-rs 加 override
