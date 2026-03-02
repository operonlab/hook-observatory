# Workshop 前端設計系統

> 建立日期：2026-02-27 | 版本：1.0 | 技術棧：React 19 + TypeScript + Rsbuild + Tailwind CSS

## 目錄
1. [色彩系統 (CSI)](#色彩系統-csi)
2. [模組品牌色](#模組品牌色)
3. [模組級主題覆蓋](#模組級主題覆蓋)
4. [排版系統](#排版系統)
5. [佈局架構](#佈局架構)
6. [間距系統](#間距系統)
7. [元件模式](#元件模式)
8. [動畫與過渡](#動畫與過渡)
9. [設計原則](#設計原則)

---

## 色彩系統 (CSI)

### 全域主題：Catppuccin Mocha

Workshop 採用 Catppuccin Mocha 深色主題為全域基礎，定義於 `workbench/src/styles/globals.css`。

#### 表面色 (Surfaces)

| 變數 | 色碼 | 用途 |
|------|------|------|
| `--base` | `#1e1e2e` | 主背景 |
| `--mantle` | `#181825` | 次級背景、捲軸軌道 |
| `--crust` | `#11111b` | 最深色表面 |
| `--surface0` | `#313244` | 浮起表面層 1（卡片、面板） |
| `--surface1` | `#45475a` | 浮起表面層 2（懸停、邊框） |

#### 文字色 (Text)

| 變數 | 色碼 | 用途 |
|------|------|------|
| `--text` | `#cdd6f4` | 主要文字 |
| `--subtext0` | `#a6adc8` | 次要文字、備註 |

#### 語義色 (Semantic Colors)

| 變數 | 色碼 | 語義 | 模組映射 |
|------|------|------|---------|
| `--blue` | `#bdd4fa` | 資訊、連結 | memvault |
| `--lavender` | `#b4befe` | 品牌、焦點 | Workshop 品牌 |
| `--accent` | `#b4befe` | 焦點環、互動指示 | 全域 |
| `--mauve` | `#cba6f7` | 創意、計劃 | taskflow |
| `--green` | `#a6e3a1` | 成功、財務 | finance |
| `--red` | `#f38ba8` | 錯誤、警告 | — |
| `--peach` | `#fab387` | 溫暖、技能 | skillpath |
| `--yellow` | `#f9e2af` | 靈感、注意 | ideagraph |
| `--teal` | `#94e2d5` | 情報、資訊 | intelflow |
| `--sky` | `#89dceb` | 輔助高亮 | — |
| `--flamingo` | `#f2cdcd` | 柔和、資源 | workpool |
| `--maroon` | `#eba0ac` | 匹配、連結 | matchcore |

#### Tailwind 映射

所有 Catppuccin 變數可透過 `bg-ctp-*`, `text-ctp-*`, `border-ctp-*` Tailwind 類別使用。定義於 `tailwind.config.cjs`。

---

## 模組品牌色

定義於 `workbench/src/shared/constants/apps.ts`，使用原始 hex 值（非 CSS 變數引用）。

| 模組 | 名稱 | 品牌色 | Catppuccin 對應 | 狀態 |
|------|------|--------|----------------|------|
| finance | 記帳理財 | `#a6e3a1` | `--green` | available |
| taskflow | 任務排程 | `#cba6f7` | `--mauve` | available |
| ideagraph | 靈感圖譜 | `#f9e2af` | `--yellow` | available |
| admin | 管理後台 | `#a6adc8` | `--subtext0` | available |
| intelflow | 情報研究 | `#94e2d5` | `--teal` | available |
| memvault | 記憶金庫 | `#bdd4fa` | `--blue` | available |
| skillpath | 技能路徑 | `#fab387` | `--peach` | coming-soon |
| workpool | 資源管理 | `#f2cdcd` | `--flamingo` | coming-soon |
| matchcore | 匹配引擎 | `#eba0ac` | `--maroon` | coming-soon |

### 動態透明度

品牌色透過 hex alpha 後綴實現透明度變體：

| 後綴 | 十進制 % | 用途 |
|------|---------|------|
| `08` | 3% | 應用選單 hover |
| `0c` | 5% | 應用選單 active |
| `14` | 8% | 首頁卡片 hover 背景 |
| `20` | 12% | 圖示容器背景 |
| `25` | 15% | 頭欄邊框 |
| `35` | 21% | 圖示容器邊框 |
| `40` | 25% | 非活躍分隔線、邊框 |
| `50` | 31% | 圖示邊框 hover |

> **重要**：這些拼接僅對原始 hex 值有效。`var(--green)40` 是無效 CSS，必須使用 `"#a6e3a1" + "40"` 或 `color-mix()`。

---

## 模組級主題覆蓋

### Memvault — 午夜神經主題 (Midnight Neural)

**檔案**：`workbench/src/modules/memvault/styles/memvault.css`
**作用域**：`.memvault` class

設計理念：保留 Catppuccin 的色相關係，但整體偏移至冷藍色調，營造「數位神經網路」氛圍。強調色降低飽和度以在深色背景上柔和呈現。

#### 表面色

| 變數 | 全域值 | 覆蓋值 | 變化 |
|------|--------|--------|------|
| `--base` | `#1e1e2e` | `#151726` | 更深、更藍 |
| `--mantle` | `#181825` | `#121422` | 更深、更藍 |
| `--crust` | `#11111b` | `#0F111E` | 更深、更藍 |
| `--surface0` | `#313244` | `#1F2240` | 更藍 |
| `--surface1` | `#45475a` | `#2B2E55` | 更藍 |
| `--surface2` | — | `#363A6A` | 新增（第三層） |

#### 文字色

| 變數 | 全域值 | 覆蓋值 |
|------|--------|--------|
| `--text` | `#cdd6f4` | `#E0E3F0` |
| `--subtext0` | `#a6adc8` | `#A2A7C4` |
| `--subtext1` | — | `#7C82A8`（新增） |

#### 強調色（Catppuccin-adjacent，柔化版）

| 變數 | 全域值 | 覆蓋值 | 設計意圖 |
|------|--------|--------|---------|
| `--blue` | `#bdd4fa` | `#9AB4F2` | 柔和天藍 |
| `--green` | `#a6e3a1` | `#92D8A6` | 柔和鼠尾草 |
| `--red` | `#f38ba8` | `#E8A0B4` | 柔和玫瑰 |
| `--mauve` | `#cba6f7` | `#BFA4F0` | 柔和丁香 |
| `--peach` | `#fab387` | `#E8B090` | 暖琥珀 |
| `--yellow` | `#f9e2af` | `#E2D4A0` | 柔和金沙 |
| `--teal` | `#94e2d5` | `#88D0C6` | 柔和海泡 |
| `--flamingo` | `#f2cdcd` | `#DEC0C8` | 柔和粉紅 |
| `--maroon` | `#eba0ac` | `#D8A0B0` | 柔和珊瑚 |

### Intelflow — 暗色奢華編輯主題 (Dark Luxury Editorial)

**檔案**：`workbench/src/modules/intelflow/styles/intelflow.css`
**作用域**：`.intelflow` class

設計理念：接近純黑的背景搭配金色品牌色，營造高端研究期刊的氛圍。所有圓角為 0，強化銳利的編輯質感。

#### 自訂變數（非 Catppuccin 覆蓋）

| 變數 | 色碼 | 用途 |
|------|------|------|
| `--if-bg` | `#0A0A0A` | 主背景（近黑） |
| `--if-bg-elevated` | `#141414` | 浮起背景 |
| `--if-bg-surface` | `#1A1A1A` | 表面背景 |
| `--if-border` | `#2A2A2A` | 邊框色 |
| `--if-accent` | `#C9A962` | 品牌金色 |
| `--if-accent-alpha` | `rgba(201,169,98,0.25)` | 品牌金色半透明 |

#### 文字層級（5 階）

| 變數 | 色碼 | 用途 |
|------|------|------|
| `--if-text` | `#FFFFFF` | 主文字 |
| `--if-text-secondary` | `#B0B0B0` | 次要文字 |
| `--if-text-tertiary` | `#848484` | 第三級文字 |
| `--if-text-muted` | `#6A6A6A` | 靜音文字 |
| `--if-text-dim` | `#4A4A4A` | 暗淡文字 |

#### 語義評分色

| 等級 | 前景色 | 背景色 |
|------|--------|--------|
| 高 (>=80%) | `#4ADE80` | `#1A2A1A` |
| 中 (>=50%) | `#FACC15` | `#2A2A1A` |
| 低 (<50%) | `#F87171` | `#2A1A1A` |

---

## 排版系統

### 字體配對

| 角色 | 字體 | 權重 | 使用場景 |
|------|------|------|---------|
| 展示 (Display) | Cormorant Garamond | 400-700 | 品牌標誌、英雄標題、模組大標題 |
| UI 本文 | System stack | 400-600 | 正文、按鈕、導航、標籤 |
| 程式碼 | JetBrains Mono | 400-500 | 技術內容、等寬排版 |
| 模組 UI | Inter (備用) | 400-500 | 模組內 UI 文字 |

System stack = `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`

### 字級階梯

| Token | 大小 | 用途 |
|-------|------|------|
| `text-[10px]` | 10px | Metadata、極小標籤 |
| `text-[11px]` | 11px | 選單註腳 |
| `text-xs` | 12px | 標籤、分類、時間戳 |
| `text-[13px]` | 13px | 導航項目 |
| `text-sm` | 14px | 正文、卡片標題 |
| `text-base` | 16px | 預設、圖示 |
| `text-lg` | 18px | 區段標題 |
| `text-2xl` | 24px | 報告標題 |
| `text-3xl` | 30px | 儀表板大數字 |
| `clamp()` | 28-40px | 響應式英雄標題 |

### 字距

| 值 | 用途 |
|-----|------|
| `0.02em` | 品牌標誌 (Workshop) |
| `0.04em` | 模組品牌名 |
| `0.1em` | 大寫後綴標籤 |
| `0.15em` | 區段標籤 (tracking-wider) |
| `0.2em` | 英雄小標題 (tracking-widest) |

---

## 佈局架構

### 應用殼層 (App Shell)

```
+---------------------------------------------+
|  AppHeader (fixed, h-48px, z-50, blur-16)   |
|  [Workshop / 模組名] <---> [切換器] [用戶]   |
+---------------------------------------------+
|                                             |
|  Content Area (pt-48px, h-screen)           |
|  +----------+----------------------+        |
|  | Sidebar  |  Main Content        |        |
|  | (220px)  |  (flex-1, scroll)    |        |
|  |          |                      |        |
|  | Module   |  <Outlet />          |        |
|  | Nav      |                      |        |
|  +----------+----------------------+        |
+---------------------------------------------+
```

- **AppShell**：固定標頭 + 滾動內容區
- **模組 Layout**：側欄（220px）+ 主內容區（flex-1）
- **頭欄**：毛玻璃效果（backdrop-blur: 16px, rgba(0,0,0,0.6)）
- **色彩跟隨**：頭欄動態跟隨當前模組品牌色

### 響應式斷點

| 斷點 | 像素 | 用途 |
|------|------|------|
| `sm` | 640px | 2 欄網格 |
| `md` | 768px | 顯示更多元素 |
| `lg` | 1024px | 3 欄網格 |
| `xl` | 1280px | 4 欄網格、兩欄佈局 |

### 網格模式

| 場景 | 模式 |
|------|------|
| 首頁應用列表 | `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3` |
| 儀表板統計 | `grid-cols-2 xl:grid-cols-4 gap-4` |
| 儀表板圖表 | `grid-cols-1 xl:grid-cols-2 gap-6` |

---

## 間距系統

### 常用內距 (Padding)

| Token | 值 | 用途 |
|-------|-----|------|
| `p-3` | 12px | 緊湊卡片 |
| `p-4` | 16px | 標準卡片 |
| `p-5` | 20px | 統計面板 |
| `p-6` | 24px | 頁面級內距 |
| `p-8` | 32px | XL 頁面內距 |

### 常用間距 (Gap)

| Token | 值 | 用途 |
|-------|-----|------|
| `gap-1` | 4px | 圖示 + 文字 |
| `gap-2` | 8px | 卡片內元素 |
| `gap-3` | 12px | 卡片間 |
| `gap-4` | 16px | 報告行列 |
| `gap-6` | 24px | 區段間、兩欄佈局 |

---

## 元件模式

### 卡片 (Card)

| 變體 | 圓角 | 背景 | 邊框 | 互動 |
|------|------|------|------|------|
| 記憶卡（標準） | 12px | `var(--mantle)` | `var(--surface0)` | hover: scale(1.02) + 邊框變色 |
| 記憶卡（緊湊） | 8px | `var(--mantle)` | `var(--surface0)` | hover: 背景微亮 |
| 統計卡 | 0 | `var(--if-bg-elevated)` | `var(--if-border)` | hover: 邊框變 accent |
| 主題卡 | 0 | `var(--if-bg-elevated)` | `var(--if-border)` | hover: 邊框變 accent |

### 按鈕 / 徽章

| 變體 | 圓角 | 樣式 |
|------|------|------|
| 篩選按鈕 | 8px | 透明 → active: color-mix(blue 12%) |
| 標籤徽章 | 0 | 透明 + 邊框 → active: 實心 accent |
| 圖示按鈕 | 6px | 透明 → hover: rgba(255,255,255,0.06) |

### 導航項目

| 狀態 | 背景 | 文字色 | 左邊框 |
|------|------|--------|--------|
| 非活躍 | 透明 | subtext1 | 2px transparent |
| 活躍 | color-mix(accent 12%) | accent | 2px solid accent |
| Hover | rgba(255,255,255,0.03) | subtext0 | 2px transparent |

---

## 動畫與過渡

### 全域預設

```css
* {
  transition: background-color 0.15s ease,
              border-color 0.15s ease,
              color 0.15s ease;
}
```

### 互動模式

| 效果 | 時間 | 屬性 | 場景 |
|------|------|------|------|
| 色彩過渡 | 150ms | background, border, color | 全域預設 |
| 卡片懸停 | 200ms | transform, border-color | 記憶卡、技能卡 |
| 條形圖展開 | 500ms | width | 儀表板水平條形圖 |
| 載入微調器 | infinite | rotate (animate-spin) | 頁面載入 |
| 摺疊展開 | 200ms | rotate | 面板摺疊箭頭 |

### 懸停效果

| 元素 | 效果 |
|------|------|
| 記憶卡 | `transform: scale(1.02)` + 邊框色變化 |
| 應用卡片 | 背景微亮 + 標題變色 + 箭頭出現 |
| 導航項目 | 背景微亮 + 文字提亮 |
| 按鈕 | 背景微亮 (rgba(255,255,255,0.06-0.08)) |

---

## 設計原則

### 1. 色彩隔離
每個模組可透過 CSS class scope（`.memvault`, `.intelflow`）覆蓋全域 Catppuccin 變數，實現獨立視覺風格而不影響其他模組。

### 2. 品牌色驅動
所有模組在導航、頭欄、卡片中的色彩從 `APP_LIST` 中央配置驅動，新增模組只需添加一個配置項。

### 3. 深色優先
所有色彩決策以深色背景為前提。強調色飽和度控制在不刺眼的範圍（Catppuccin-adjacent），避免使用 Tailwind 400 級色彩。

### 4. 語義分層
- **表面**：3 層深度（base → surface0 → surface1）
- **文字**：3-5 層（取決於模組複雜度）
- **強調色**：語義映射（成功=綠、錯誤=紅、資訊=藍）

### 5. 漸進式增強
- 全域 150ms 過渡確保基本互動回饋
- 卡片懸停提供 scale + 色彩雙重回饋
- 毛玻璃效果（backdrop-blur）用於浮層

### 6. CSS 變數 + Tailwind 混合
- **動態色彩**（模組品牌色 + 透明度）→ inline styles
- **固定佈局**（flex, grid, padding, margin）→ Tailwind classes
- **主題覆蓋** → CSS 變數 + scope class

---

## 檔案索引

| 檔案 | 用途 |
|------|------|
| `src/styles/globals.css` | 全域 Catppuccin 主題（19 變數） |
| `src/shared/constants/apps.ts` | 9 模組品牌色配置 |
| `src/modules/memvault/styles/memvault.css` | 午夜神經主題（19 覆蓋 + 2 新增） |
| `src/modules/intelflow/styles/intelflow.css` | 暗色奢華編輯主題（22 自訂變數） |
| `tailwind.config.cjs` | Tailwind <-> CSS 變數映射 |
| `src/shell/AppHeader.tsx` | 模組色彩跟隨邏輯 |
| `src/shell/AppLauncher.tsx` | 應用切換器色彩邏輯 |
| `src/pages/Home.tsx` | 首頁應用卡片配色 |

---

> 本文件為 Workshop 前端設計系統的單一真實來源 (Single Source of Truth)。
> 所有配色修改應先更新此文件，再同步至程式碼。
