# auth — 登入與帳號設定 UI

> 登入頁面、OAuth 回調處理、帳號設定。

## 路由

| 路徑 | 頁面 | 說明 |
|------|------|------|
| `/login` | LoginPage | Email/Password + Google/GitHub OAuth 按鈕 |
| `/auth/callback/:provider` | OAuthCallback | OAuth 回調處理（自動跳轉） |
| `/settings/account` | AccountSettings | 修改密碼、綁定/解綁 OAuth |

## 元件

```
workbench/src/modules/auth/
├── pages/
│   ├── LoginPage.tsx          # 登入頁（三種方式）
│   ├── OAuthCallback.tsx      # OAuth 回調中繼頁
│   └── AccountSettings.tsx    # 帳號設定頁
├── components/
│   ├── LoginForm.tsx          # Email + Password 表單
│   ├── OAuthButtons.tsx       # Google / GitHub 登入按鈕
│   └── LinkedAccounts.tsx     # 已連結 OAuth 帳號列表
├── hooks/
│   └── useAuth.ts             # 登入狀態、登出、權限檢查
├── stores/
│   └── authStore.ts           # Zustand：currentUser, isAuthenticated, permissions
├── api/
│   └── authApi.ts             # login(), logout(), getMe(), oauth()
└── index.tsx                  # 匯出路由
```

## 參考

- [Auth 後端模組](../../../core/src/modules/auth/README.md)
- [P4 藍圖](../../../docs/blueprint/p4-auth.md)
