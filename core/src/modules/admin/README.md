# admin — 平台管理模組

> Workshop 平台的管理後台——使用者管理、模組控制、系統配置、稽核日誌。

## 定位

| 屬性 | 值 |
|------|-----|
| **Schema** | `admin` |
| **依賴** | auth |
| **被依賴** | 無（唯讀觀察者，不寫入其他模組） |
| **MCP** | `workshop-admin`（待建） |
| **V1 參考** | V1 有 sysmon + agent-metrics，已併入 gateway |

## 核心功能

### 使用者管理

- 使用者列表（狀態篩選、搜尋、分頁）
- 使用者詳情（角色、OAuth 連結、session 歷史）
- 待審核列表（approve / reject 操作）
- 狀態操控（active ↔ suspended → banned）
- 角色指派（admin / user / guest）

### 模組控制

- 模組啟用/停用（按 space 設定）
- 模組健康狀態（API 回應時間、錯誤率）

### 系統配置

- 全域設定管理（JSON 配置 + UI 編輯）
- 環境資訊檢視（版本、依賴、連線狀態）

### 稽核日誌

- 所有管理操作自動記錄
- 事件類型：登入/登出、角色變更、狀態變更、設定變更
- 可搜尋、可匯出

## DB Schema

```sql
CREATE SCHEMA admin;

admin.audit_logs        -- 稽核日誌（actor_id, action, target_type, target_id, details JSONB, ip, created_at）
admin.system_config     -- 系統配置（key, value JSONB, updated_by, updated_at）
```

`admin` 模組從其他模組 **讀取** 資料（透過 service imports），但 **不寫入** 其他模組的 schema。

## API 端點

| 方法 | 路徑 | 用途 |
|------|------|------|
| GET | `/api/admin/users` | 使用者列表（分頁+過濾） |
| GET | `/api/admin/users/{id}` | 使用者詳情 |
| POST | `/api/admin/users/{id}/approve` | 核准待審核使用者 |
| POST | `/api/admin/users/{id}/reject` | 拒絕待審核使用者 |
| POST | `/api/admin/users/{id}/suspend` | 停權 |
| POST | `/api/admin/users/{id}/unsuspend` | 解除停權 |
| POST | `/api/admin/users/{id}/ban` | 封鎖（永久） |
| PUT | `/api/admin/users/{id}/role` | 變更角色 |
| GET | `/api/admin/audit` | 稽核日誌（分頁+過濾） |
| GET | `/api/admin/config` | 系統配置 |
| PUT | `/api/admin/config/{key}` | 更新配置 |
| GET | `/api/admin/health` | 系統健康狀態 |
| GET | `/api/admin/modules` | 模組狀態列表 |
| POST | `/api/admin/modules/{name}/toggle` | 啟用/停用模組 |

## 目錄結構

```
core/src/modules/admin/
├── __init__.py
├── routes.py         # 所有 API 端點（require_permission("admin.*")）
├── models.py         # audit_logs, system_config
├── schemas.py        # Pydantic request/response
├── services.py       # 公開 API（使用者管理、稽核、配置）
├── events.py         # admin.user.approved, admin.user.suspended 等
└── deps.py           # require_admin（admin 角色限定）
```

## 事件

| 事件 | 觸發時機 |
|------|---------|
| `admin.user.approved` | 管理員核准使用者 |
| `admin.user.suspended` | 管理員停權使用者 |
| `admin.user.banned` | 管理員封鎖使用者 |
| `admin.user.role_changed` | 管理員變更角色 |
| `admin.config.updated` | 系統配置變更 |

## 安全

- 所有 admin 端點要求 `admin` 角色（`@require_permission("admin.*")`）
- 所有操作寫入 `audit_logs`（含 actor IP、user-agent）
- 不提供批量刪除使用者功能（防誤操作）

## 參考文件

- [P4 藍圖](../../docs/blueprint/p4-auth.md) — Auth + Admin 建設計畫
- [服務目錄](../../docs/vision/domain-catalog.md) — admin 定位
