# Route A 精簡版建模指南

> 11 圖層 / 16 參數 / Cubism FREE 限制內
> PSD: `fairy_cubism.psd` (2048×2048, 11 layers)

---

## 1. 圖層一覽

| # | PSD 圖層名 | 來源 | 用途 |
|---|-----------|------|------|
| 1 | book | Florence-2 | 魔法書（幾乎靜態） |
| 2 | wing_left | remainder 拆分 | 左翅（物理搖擺） |
| 3 | wing_right | remainder 拆分 | 右翅（物理搖擺） |
| 4 | body_effects | remainder 拆分 | 袖子、手臂、身體輪廓 |
| 5 | legs | Florence-2 | 腿部（靜態） |
| 6 | dress | Florence-2 | 連身裙 |
| 7 | face | Florence-2 | 臉部底層（嘴巴透過 mesh 變形） |
| 8 | left_eye | Florence-2 | 左眼整顆（縮放=眨眼） |
| 9 | right_eye | Florence-2 | 右眼整顆（縮放=眨眼） |
| 10 | silver_hair | Florence-2 | 銀灰色頭髮（物理搖擺） |
| 11 | star_clip | Florence-2 | 星形髮夾（物理搖擺） |

繪製順序：1(最後) → 11(最前)

---

## 2. 參數設定（16 個，FREE 限制 30）

### P0 — 必做（9 個）

| 參數 ID | 範圍 | 預設 | 綁定目標 | 實作方式 |
|---------|------|------|---------|---------|
| ParamAngleX | -30~30 | 0 | 頭部整體 | Warp Deformer 控制 face+eyes+hair |
| ParamAngleY | -30~30 | 0 | 頭部整體 | 同上，Y 軸 |
| ParamAngleZ | -30~30 | 0 | 頭部整體 | Rotation Deformer |
| ParamEyeLOpen | 0~1 | 1 | left_eye | ArtMesh Y 軸縮放（1=全開, 0=壓扁=閉眼） |
| ParamEyeROpen | 0~1 | 1 | right_eye | 同上 |
| ParamEyeBallX | -1~1 | 0 | left_eye + right_eye | ArtMesh 水平位移 |
| ParamEyeBallY | -1~1 | 0 | left_eye + right_eye | ArtMesh 垂直位移 |
| ParamMouthOpenY | 0~1 | 0 | face 的嘴巴區域 | face ArtMesh 局部 mesh 變形 |
| ParamBodyAngleX | -10~10 | 0 | 全身 | Warp Deformer 控制 body 群組 |

### P1 — 建議（4 個）

| 參數 ID | 範圍 | 預設 | 綁定目標 |
|---------|------|------|---------|
| ParamMouthForm | -1~1 | 0 | face 嘴巴區域 mesh |
| ParamBodyAngleY | -10~10 | 0 | 全身前後傾 |
| ParamArmRAng | 0~1 | 0 | body_effects 右手區域 mesh |
| ParamHairFront | -1~1 | 0 | silver_hair mesh（物理驅動） |

### P2 — 物理用（3 個，自動驅動不佔互動預算）

| 參數 ID | 範圍 | 預設 | 綁定目標 |
|---------|------|------|---------|
| ParamWingL | -1~1 | 0 | wing_left mesh |
| ParamWingR | -1~1 | 0 | wing_right mesh |
| ParamStarHairpin | -1~1 | 0 | star_clip mesh |

---

## 3. Deformer 結構（預估 8 個，FREE 限制 50）

```
ROOT
├── [Warp] head_deformer          ← ParamAngleX/Y 驅動
│   ├── [Rotation] head_rotate    ← ParamAngleZ 驅動
│   │   ├── face (ArtMesh)
│   │   ├── left_eye (ArtMesh)
│   │   ├── right_eye (ArtMesh)
│   │   └── star_clip (ArtMesh)
│   └── silver_hair (ArtMesh)     ← ParamHairFront 也影響
│
├── [Warp] body_deformer          ← ParamBodyAngleX/Y 驅動
│   ├── dress (ArtMesh)
│   ├── body_effects (ArtMesh)    ← ParamArmRAng 局部 mesh
│   └── legs (ArtMesh)
│
├── wing_left (ArtMesh)           ← ParamWingL 驅動
├── wing_right (ArtMesh)          ← ParamWingR 驅動
└── book (ArtMesh)                ← 靜態或微弱 body 跟隨
```

---

## 4. Cubism Editor 操作步驟

### 4.1 匯入 PSD

1. 開啟 Cubism Editor 5.3
2. `檔案` → `開啟` → 選擇 `fairy_cubism.psd`
3. Cubism 會自動為每個圖層建立 ArtMesh
4. 確認 11 個 ArtMesh 都正確載入

### 4.2 自動網格（AI Auto Mesh）

> Cubism 5.3 新功能：自動產生高品質網格

1. 選取所有 ArtMesh
2. 右鍵 → `自動網格生成`（或 Ctrl+Shift+A）
3. face 和 eyes 手動加密：雙擊 ArtMesh → 增加嘴巴區域頂點密度

### 4.3 建立 Deformer

1. 選取 face + left_eye + right_eye + star_clip
2. `建模` → `建立翻轉變形器` → 命名 `head_rotate`
3. 再包一層 `建立彎曲變形器` → 命名 `head_deformer`
4. 對 body 群組重複（dress + body_effects + legs → `body_deformer`）

### 4.4 眨眼設定（關鍵！）

Route A 的眼睛是整顆圖層，沒有分虹膜/瞳孔。眨眼用 **Y 軸縮放**：

1. 選取 `left_eye` ArtMesh
2. 新增參數 `ParamEyeLOpen`
3. 在 0 的位置：將 ArtMesh 的上下頂點向中心壓縮（模擬閉眼）
4. 在 1 的位置：保持原始形狀
5. 對 `right_eye` 重複（用 `ParamEyeROpen`）

### 4.5 嘴巴設定（在 face 上做 mesh 變形）

1. 在 `face` ArtMesh 的嘴巴區域增加頂點密度（至少 4×3 格）
2. 新增參數 `ParamMouthOpenY`
3. 在 0：嘴巴頂點保持原位（閉嘴）
4. 在 1：下方頂點向下拉（張嘴），可見 face 底色模擬口腔

### 4.6 物理設定

匯入 `fairy.physics3.json`，或在 Editor 中手動設定：

| 物理群組 | 輸入 | 輸出 | 特性 |
|---------|------|------|------|
| 前髮 | ParamAngleX (×0.4) | ParamHairFront | 2 段擺錘，阻力 0.5/0.8 |
| 左翅 | ParamAngleX (×0.3) | ParamWingL | 單段，輕盈（阻力 0.3） |
| 右翅 | ParamAngleX (×0.3) | ParamWingR | 同上，Reflect=true |
| 髮夾 | ParamAngleX (×0.15) | ParamStarHairpin | 單段，偏硬（阻力 0.7） |

---

## 5. 表情與動作檔

### 已生成的表情（7 個）

| 檔案 | 效果 |
|------|------|
| exp_idle.exp3.json | 預設（空） |
| exp_happy.exp3.json | 微笑 + 瞇眼 |
| exp_thinking.exp3.json | 閉眼 + 低頭 |
| exp_speaking.exp3.json | 半開嘴 + 微笑 |
| exp_surprised.exp3.json | 圓眼 + 張嘴 |
| exp_wink_L.exp3.json | 左眼閉 |
| exp_wink_R.exp3.json | 右眼閉 |

### 已生成的動作（4 個）

| 檔案 | 時長 | 循環 | 描述 |
|------|------|------|------|
| idle.motion3.json | 6s | ✓ | 輕微搖擺 + 眨眼 + 眼球微動 |
| thinking.motion3.json | 4s | ✓ | 閉眼 + 低頭 + 頭微傾 |
| speaking.motion3.json | 3s | ✓ | 口型開合節奏（配合 LipSync） |
| wave.motion3.json | 5s | ✗ | 右手舉起揮 3 次 + 笑 |

---

## 6. Route A 限制與取捨

| 項目 | 完整版（40 層） | Route A（11 層） |
|------|----------------|-----------------|
| 眼球轉動 | 虹膜+瞳孔獨立 mesh | 整顆眼睛位移（效果較平） |
| 嘴巴 | 獨立上下唇+牙齒 | face mesh 局部變形（無牙齒） |
| 眉毛 | 獨立圖層，可形變 | 無（被 face 覆蓋） |
| 翅膀 | 四瓣各自獨立 | 左右各一瓣（含粒子） |
| 手臂 | 上臂/前臂/手掌獨立 | body_effects 整體 mesh |
| 粒子特效 | 獨立動畫圖層 | 隨翅膀/body 一起動 |

**建議**：先用 Route A 跑通整個 Cubism → moc3 → WebGL pipeline。
如果效果不滿意，之後可以在 Cubism Editor 中手動拆分圖層（用橡皮擦 + 新圖層複製）。

---

## 7. 匯出 Checklist

- [ ] `fairy.moc3` — 主模型檔
- [ ] `textures/` — 紋理圖集（Cubism 自動打包）
- [ ] 在 Cubism Viewer 驗證 4 個動作
- [ ] 物理播放測試：拖拽頭部，觀察翅膀/頭髮搖擺
- [ ] 眨眼測試：EyeBlink 群組自動觸發
- [ ] LipSync 測試：嘴巴開合是否自然
