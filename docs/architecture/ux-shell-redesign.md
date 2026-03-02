# UX Shell 架構重塑

> ADR-2026-02-27 | 狀態：已批准

## 背景

Workshop workbench 最初採用傳統 Shell 架構：全域 NavBar（56px 固定頂部）+ 左側 Sidebar（240px/64px 可收合）+ padded content area。所有 10 個模組共用同一框架。

隨著 Intelflow（暗色奢華主題）和 Memvault（深藍神經主題）等模組加入自己的視覺風格，Shell 框架成為限制：

1. **雙層導航冗餘**：Global Sidebar + Module 內部導航，佔用過多螢幕空間
2. **主題衝突**：Catppuccin 全域背景與模組自有主題之間產生邊框/間隙
3. **沉浸感不足**：padding + sidebar 讓模組像「被框住的子頁面」

## 決策

採用「App Launcher + Full-Screen Module + App Switcher」架構，參考 Google Workspace 生態系設計。

### Before（舊架構）

```
┌─────────────────────────────────────────┐
│  NavBar: "Workshop" logo + user + logout│  56px
├────────┬────────────────────────────────┤
│ Global │                                │
│Sidebar │  Module Content                │
│ 240px  │  (padded, constrained)         │
│        │                                │
│ 📋 📊  │                                │
│ 💡 🧠  │                                │
└────────┴────────────────────────────────┘
```

### After（新架構）

```
┌─────────────────────────────────────────────────┐
│                            [⌂] [⊞] [J] [登出]  │  Glass Header 48px
├─────────────────────────────────────────────────┤
│ Module Tab Bar (由各模組自行定義)                  │
├─────────────────────────────────────────────────┤
│                                                 │
│  Module Content                                 │
│  (full-screen, own theme, no padding)           │
│                                                 │
└─────────────────────────────────────────────────┘
```

## 核心變更

### 1. 路由重構

| 路徑 | 舊行為 | 新行為 |
|------|--------|--------|
| `/` | Home（含 Sidebar） | Redirect → `/apps` |
| `/apps` | 不存在 | App Launcher grid |
| `/<module>/*` | Layout 包裝（NavBar + Sidebar + padding） | AppShell 包裝（Glass Header，無 Sidebar，無 padding） |

### 2. App Shell（替代 Layout）

`shell/AppShell.tsx` — 極簡包裝：
- Glass morphism header：`bg-black/50 backdrop-blur-[12px]`
- 僅提供 `pt-12 h-screen > h-full overflow-y-auto` 容器
- 無 Sidebar、無 padding、無 margin-left

### 3. App Header（替代 NavBar）

`shell/AppHeader.tsx` — 48px 固定 glass header：
- Left：Home icon（返回 `/apps`）
- Right：App Switcher（九宮格 dropdown）、User avatar（name initial）、Logout

### 4. App Switcher（升級 AppLauncher）

`shell/AppLauncher.tsx` — 九宮格 dropdown：
- 2x3 grid 顯示可用模組
- 底部「全部應用 →」連回 `/apps`
- Click-outside-close

### 5. 模組主題隔離

各模組可透過 CSS scope 定義自有主題，不影響其他模組：

| 模組 | CSS Scope | 主題 |
|------|-----------|------|
| Intelflow | `.intelflow` | Dark Luxury (#0A0A0A, gold accent #C9A962) |
| Memvault | `.memvault` | Midnight Neural (#0B0D1A, violet accent #7C8FFF) |
| 其他模組 | 無（使用全域 Catppuccin） | Catppuccin Mocha (#1e1e2e) |

**CSS Variable Scoping 技巧**：Memvault 在 `.memvault` scope 內重新定義 Catppuccin CSS 變數（`--base`, `--mantle`, `--text` 等），現有 14 個元件自動套用新主題，零程式碼改動。

## 技術決策

### Glass Header 設計

選擇 `bg-black/50 + backdrop-blur-12px` 而非實色背景：
- 在 Catppuccin (#1e1e2e)、Intelflow (#0A0A0A)、Memvault (#0B0D1A) 上都和諧
- 不需要為每個模組主題定制 header 顏色
- 48px 高度比舊 NavBar (56px) 更緊湊

### h-full Chain 保證

```
<AppHeader />                              fixed z-50, 48px
<div class="pt-12 h-screen">              AppShell: 100vh
  <div class="h-full overflow-y-auto">    唯一 scrollbar
    <div class="memvault flex flex-col h-full min-h-full">
      <nav class="sticky top-0 shrink-0"> Module Tab Bar
      <div class="flex-1 overflow-y-auto"> Module content
```

只有一個 scrollbar（AppShell 的 `overflow-y-auto`），不會出現雙層滾動。

## 檔案影響

### 新增（5 files）
- `shell/AppHeader.tsx` — Glass Header
- `shell/AppShell.tsx` — 極簡包裝
- `memvault/styles/memvault.css` — Midnight Neural 主題
- `memvault/components/MemvaultLayout.tsx` — Tab Bar layout
- `docs/architecture/ux-shell-redesign.md` — 本文件

### 修改（5 files）
- `App.tsx` — 路由重構
- `shell/AppLauncher.tsx` — 定位調整
- `pages/Home.tsx` — Full-bleed 調整
- `memvault/pages/browser.tsx` — 移除冗餘 header/nav
- `memvault/pages/galaxy.tsx` — 移除「返回列表」按鈕

### 刪除（3 files）
- `shell/Layout.tsx`
- `shell/Sidebar.tsx`
- `shell/NavBar.tsx`

### 更新（1 file）
- `docs/architecture/frontend.md` — Shell 描述段落

## 驗證計畫

1. `BASE_PATH=/v2 pnpm build` — 零編譯錯誤
2. `/` → redirect `/apps` → App Launcher grid
3. Intelflow → 全螢幕 #0A0A0A，Tab Bar 正常
4. Memvault → 全螢幕 #0B0D1A，Tab Bar 正常
5. Glass Header — 在所有主題上清晰可讀
6. App Switcher — 九宮格展開/收合正常
7. RWD — 375px / 768px / 1440px
8. h-full chain — 單一 scrollbar
9. 登出功能正常
