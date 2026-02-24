# admin — 平台管理 UI

> 使用者管理、稽核日誌、系統配置、模組控制。

## 路由

| 路徑 | 頁面 | 說明 |
|------|------|------|
| `/admin` | Dashboard | 系統概覽（使用者數、待審核數、模組狀態） |
| `/admin/users` | UserList | 使用者列表（狀態篩選、搜尋、分頁） |
| `/admin/users/pending` | PendingList | 待審核列表（approve / reject） |
| `/admin/users/:id` | UserDetail | 使用者詳情（角色、OAuth、session 歷史） |
| `/admin/audit` | AuditLog | 稽核日誌（時間範圍、事件類型過濾） |
| `/admin/config` | SystemConfig | 系統配置編輯 |
| `/admin/modules` | ModuleStatus | 模組健康狀態與啟停控制 |

## 元件

```
workbench/src/modules/admin/
├── pages/
│   ├── Dashboard.tsx           # 系統總覽卡片
│   ├── UserList.tsx            # 使用者表格（DataTable）
│   ├── PendingList.tsx         # 待審核列表（Approve/Reject 按鈕）
│   ├── UserDetail.tsx          # 使用者詳情（角色操控、狀態變更）
│   ├── AuditLog.tsx            # 稽核日誌表格（時間軸 + 過濾）
│   ├── SystemConfig.tsx        # 配置表單（JSON editor）
│   └── ModuleStatus.tsx        # 模組健康卡片列表
├── components/
│   ├── UserStatusBadge.tsx     # 4 狀態彩色 badge
│   ├── UserRoleSelect.tsx      # 角色下拉選單
│   ├── UserActionMenu.tsx      # 操作選單（approve/suspend/ban）
│   ├── AuditLogEntry.tsx       # 單筆稽核紀錄
│   ├── OAuthProviderList.tsx   # OAuth 綁定列表
│   └── ModuleHealthCard.tsx    # 模組狀態卡片
├── hooks/
│   ├── useUsers.ts
│   ├── useAuditLog.ts
│   └── useModules.ts
├── stores/
│   └── adminStore.ts           # Zustand
├── api/
│   └── adminApi.ts
└── index.tsx
```

## 存取限制

- 所有 admin 頁面需 `admin` 角色
- 前端 route guard：`<ProtectedRoute role="admin">`
- 非 admin 使用者導向 403 頁面

## 參考

- [Admin 後端模組](../../../core/src/modules/admin/README.md)
- [P4 藍圖](../../../docs/blueprint/p4-auth.md)
