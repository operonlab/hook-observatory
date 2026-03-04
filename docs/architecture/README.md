---
doc_version: 1
content_hash: pending
target_lang: zh-TW
---

# 系統架構文件

> Workshop 的核心設計決策、架構模式與技術規格。

---

## 架構決策紀錄 (ADR)

所有 ADR 集中在 [architecture-decisions.md](./architecture-decisions.md)：

| ADR | 標題 | 涵蓋範圍 |
|-----|------|---------|
| AD-1 | Modular Monolith | [modular-monolith.md](./modular-monolith.md) |
| AD-2 | SDK-Based Protocol Adapter | [composite-architecture.md](./composite-architecture.md) |
| AD-3 | Space Model + RBAC | [auth.md](./auth.md) |
| AD-4 | Widget Manifest | [widget-manifest-spec.md](./widget-manifest-spec.md) |
| AD-5 | Resource Taxonomy | [../vision/domain-catalog.md](../vision/domain-catalog.md) |
| AD-6 | Event-Driven Architecture | [event-driven.md](./event-driven.md) |
| AD-7 | Progressive Enhancement | [rwd-pwa.md](./rwd-pwa.md) |
| AD-8 | Plugin System | [plugin-system.md](./plugin-system.md) |
| AD-9 | Python-First + Selective Rust | [tech-stack.md](./tech-stack.md) |
| AD-10 | Event Resilience | [event-resilience-patterns.md](./event-resilience-patterns.md) |
| AD-11 | FSM Agent Guardrail | — |

---

## 後端架構

| 文件 | 內容 |
|------|------|
| [modular-monolith.md](./modular-monolith.md) | 模組化單體架構、模組邊界規則、13 模組權限歸屬 |
| [event-driven.md](./event-driven.md) | 事件結構、命名規範、EventBus API、事件流範例 |
| [event-resilience-patterns.md](./event-resilience-patterns.md) | 6 個事件韌性模式（P1-P6）— 時效分類、冪等投影、WAL 分離等 |
| [shared-layer-patterns.md](./shared-layer-patterns.md) | OOP 模式：BaseCRUDService、SpaceScopedModel、SoftDeleteMixin、PaginatedResponse |
| [auth.md](./auth.md) | 認證（signed cookies）+ 授權（RBAC + ABAC）+ 使用者生命週期 |
| [notification.md](./notification.md) | 通知路由、多通道推播、雙向平台橋接 |
| [communication.md](./communication.md) | 通訊模式：HTTP REST / SSE / WebRTC / Event Bus |
| [composite-architecture.md](./composite-architecture.md) | SDK → CLI → MCP → Skill 四層複合架構 |
| [four-tier-data-lifecycle.md](./four-tier-data-lifecycle.md) | 熱暖冷冰四層資料生命週期策略 |
| [scheduling.md](./scheduling.md) | 系統排程管理：開機自起、離線自救、定時任務 |

## 前端架構

| 文件 | 內容 |
|------|------|
| [frontend.md](./frontend.md) | React 19 三層架構：SPA 頁面 + Dashboard + LLM Chat |
| [frontend-design-system.md](./frontend-design-system.md) | Catppuccin Mocha 主題、模組色彩系統 |
| [ux-shell-redesign.md](./ux-shell-redesign.md) | App Launcher + Full-Screen Module 架構（ADR-2026-02-27） |
| [widget-manifest-spec.md](./widget-manifest-spec.md) | Dashboard Widget 系統設計規格（AD-4 延伸） |
| [rwd-pwa.md](./rwd-pwa.md) | RWD 斷點、PWA manifest、觸控目標 |

## 基礎設施

| 文件 | 內容 |
|------|------|
| [tech-stack.md](./tech-stack.md) | 技術選型：Python 3.12、FastAPI、React 19、PostgreSQL 17 |
| [folder-structure.md](./folder-structure.md) | 目錄結構、命名規則、三層分類（Core / Stations / Bridges） |
| [observability.md](./observability.md) | OpenTelemetry + LGTM (dev) / SigNoz (prod) |
| [plugin-system.md](./plugin-system.md) | Hook 引擎 + 插件 Manifest + 沙盒執行 |

## 設計原則

| 文件 | 內容 |
|------|------|
| [principles.md](./principles.md) | KISS、YAGNI、SRP、DRY、SSOT 等設計原則 |
