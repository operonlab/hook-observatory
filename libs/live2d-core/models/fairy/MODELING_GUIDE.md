# Live2D 精靈吉祥物建模指南

> 角色：銀灰短髮精靈少女（「仙子」）
> 工具：Live2D Cubism Editor 5.x
> 目標：WebGL 即時渲染，搭配 Workshop AI 助手系統

---

## 目錄

1. [參考圖一覽](#1-參考圖一覽)
2. [PSD 分層拆解指南](#2-psd-分層拆解指南)
3. [Cubism Editor — 網格與綁定](#3-cubism-editor--網格與綁定)
4. [參數設定指南](#4-參數設定指南)
5. [物理模擬設定](#5-物理模擬設定)
6. [表情設定](#6-表情設定)
7. [動作錄製（4 個 Motion）](#7-動作錄製4-個-motion)
8. [匯出清單](#8-匯出清單)
9. [目錄結構規範](#9-目錄結構規範)

---

## 1. 參考圖一覽

| 動作狀態 | 檔案 | 特徵描述 |
|---------|------|---------|
| 待機（Idle） | `reference/idle.png` | 睜眼直視，表情平靜，坐姿端正 |
| 思考（Thinking） | `reference/thinking.png` | 閉眼，左手托腮，嘴微抿 |
| 說話（Speaking） | `reference/speaking.png` | 開口說話，右手食指指向上方，眉毛微揚 |
| 揮手（Wave） | `reference/wave.png` | 右手高舉揮手，開心大笑，身體略微前傾 |

### 角色視覺特徵摘要

- **髮色**：銀灰色（偏淡紫色調）短髮，瀏海輕柔下垂
- **眼睛**：深紫色大眼，高光明顯，虹膜有漸層
- **髮飾**：右側黃色五角星髮夾（立體感強，有光澤）
- **翅膀**：半透明蝴蝶翅膀，帶淡紫/藍色光暈，四瓣造型
- **服裝**：深藍色/深紫色無袖連身裙，胸前有星形圖案，配白色蕾絲膨袖（可拆件）
- **坐騎**：一本厚重的魔法書（深色封面，書頁發光）
- **環境粒子**：背景有閃亮星形光點、光暈效果

---

## 2. PSD 分層拆解指南

### 2.1 準備工作

在 Photoshop（或 Clip Studio Paint）中，以 `wave.png`（揮手圖）為主要拆解基礎，因為它包含最多動態部位（舉起的手、翅膀展開、身體傾斜）。

**畫布設定**：
- 尺寸：2048 × 2048 px（Live2D 最佳紋理尺寸）
- 解析度：72 DPI
- 色彩模式：RGB 8-bit

### 2.2 圖層結構（由上到下）

```
ROOT
├── [GROUP] 前景粒子
│   ├── star_particle_front_01    ← 前景閃光星（動畫用）
│   └── star_particle_front_02
│
├── [GROUP] 頭部
│   ├── star_hairpin               ← 星形髮夾（獨立物件，物理搖擺）
│   ├── [GROUP] 瀏海前層
│   │   ├── hair_bang_left         ← 左側瀏海（物理）
│   │   ├── hair_bang_center       ← 中間瀏海
│   │   └── hair_bang_right        ← 右側瀏海（物理）
│   ├── [GROUP] 眼睛（左）
│   │   ├── eye_L_lash_upper       ← 上睫毛
│   │   ├── eye_L_lash_lower       ← 下睫毛
│   │   ├── eye_L_white            ← 眼白
│   │   ├── eye_L_iris             ← 虹膜（漸層）
│   │   ├── eye_L_pupil            ← 瞳孔
│   │   └── eye_L_highlight        ← 高光（不隨眼球移動）
│   ├── [GROUP] 眼睛（右）         ← 同上左眼結構，鏡像
│   │   ├── eye_R_lash_upper
│   │   ├── eye_R_lash_lower
│   │   ├── eye_R_white
│   │   ├── eye_R_iris
│   │   ├── eye_R_pupil
│   │   └── eye_R_highlight
│   ├── [GROUP] 眉毛
│   │   ├── brow_L                 ← 左眉
│   │   └── brow_R                 ← 右眉
│   ├── [GROUP] 嘴巴
│   │   ├── mouth_upper            ← 上唇（含人中）
│   │   ├── mouth_lower            ← 下唇
│   │   ├── mouth_teeth            ← 牙齒（說話/大笑時可見）
│   │   └── mouth_tongue           ← 舌頭（大笑時）
│   ├── nose                       ← 鼻子（輕微標示）
│   ├── blush_L                    ← 左臉紅暈
│   ├── blush_R                    ← 右臉紅暈
│   └── face_base                  ← 臉部底層（輪廓）
│
├── [GROUP] 頭髮（後層）
│   ├── hair_back_left             ← 後方左側髮束（物理）
│   ├── hair_back_right            ← 後方右側髮束（物理）
│   └── hair_crown                 ← 頭頂髮（固定）
│
├── [GROUP] 翅膀
│   ├── wing_upper_L               ← 左上翅（物理）
│   ├── wing_lower_L               ← 左下翅（物理）
│   ├── wing_upper_R               ← 右上翅（物理）
│   ├── wing_lower_R               ← 右下翅（物理）
│   └── wing_glow                  ← 翅膀光暈（加法混合）
│
├── [GROUP] 身體
│   ├── [GROUP] 右手（揮手用）
│   │   ├── arm_R_upper            ← 右上臂
│   │   ├── arm_R_lower            ← 右前臂
│   │   └── hand_R                 ← 右手掌（含手指）
│   ├── [GROUP] 左手
│   │   ├── arm_L_upper            ← 左上臂
│   │   ├── arm_L_lower            ← 左前臂
│   │   └── hand_L                 ← 左手掌
│   ├── dress_front                ← 連身裙前片
│   ├── dress_star_emblem          ← 胸前星形圖案
│   ├── sleeve_L                   ← 左蕾絲袖
│   ├── sleeve_R                   ← 右蕾絲袖
│   └── body_base                  ← 身體底層
│
├── [GROUP] 腿部
│   ├── leg_L                      ← 左腳（坐姿）
│   └── leg_R                      ← 右腳（坐姿）
│
├── [GROUP] 魔法書
│   ├── book_pages_glow            ← 書頁發光（加法混合）
│   ├── book_cover                 ← 書封
│   └── book_shadow                ← 書下陰影
│
└── [GROUP] 背景粒子
    ├── star_particle_bg_01        ← 背景星形（動畫用）
    ├── star_particle_bg_02
    └── bg_glow                    ← 整體光暈
```

### 2.3 分層注意事項

**透明度處理**：
- 翅膀圖層設為「相加（Add）」混合模式，讓半透明效果在白色背景與深色背景上都能正確顯示
- 光暈圖層（wing_glow, bg_glow）同樣使用加法混合

**邊緣處理**：
- 所有可動部位（眼睛、眉毛、嘴巴、手臂）邊緣必須留有 **至少 20px 的透明緩衝區**，以避免變形時出現截邊

**遮罩（Clipping Mask）準備**：
- 虹膜、瞳孔、高光需建立剪切遮罩至眼白圖層，讓眼球在邊界內移動

---

## 3. Cubism Editor — 網格與綁定

### 3.1 網格密度建議

| 部位 | 網格密度 | 理由 |
|------|---------|------|
| 眼睛（虹膜、瞳孔） | 高（4×4 以上） | 需要平滑的眼球轉動 |
| 嘴巴 | 高（口腔形狀複雜） | 開口、微笑、說話形變 |
| 臉部底層 | 中（均勻分佈） | 頭部角度轉動 |
| 翅膀 | 中（延放射狀） | 煽動動作自然 |
| 頭髮 | 中（沿髮絲走向） | 物理搖曳 |
| 手臂 | 低～中 | 主要靠關節旋轉 |
| 魔法書 | 低 | 幾乎靜態 |

### 3.2 變形器（Deformer）層次

```
ArtMesh 群組
├── 翻轉變形器：head_angle  （控制頭部 X/Y/Z 角度）
│   ├── 彎曲變形器：face_rotate
│   │   ├── face_base
│   │   ├── nose
│   │   ├── blush_L / blush_R
│   │   └── 眼睛群組（含所有子圖層）
│   └── 眉毛群組
├── 彎曲變形器：body_sway  （控制身體左右搖擺）
│   ├── body_base
│   ├── dress_front
│   ├── arm_L 群組
│   └── arm_R 群組
└── 旋轉變形器：wing_L_upper（翅膀各瓣獨立）
    └── ...
```

---

## 4. 參數設定指南

### 4.1 核心參數列表

| 參數 ID | 名稱 | 範圍 | 預設值 | 說明 |
|---------|------|------|--------|------|
| `ParamAngleX` | 頭部左右角度 | -30 ～ 30 | 0 | 負值=向左，正值=向右 |
| `ParamAngleY` | 頭部上下角度 | -30 ～ 30 | 0 | 負值=低頭，正值=抬頭 |
| `ParamAngleZ` | 頭部旋轉（傾斜） | -30 ～ 30 | 0 | 整頭歪斜 |
| `ParamEyeBallX` | 眼球左右 | -1 ～ 1 | 0 | 兩眼同步水平移動 |
| `ParamEyeBallY` | 眼球上下 | -1 ～ 1 | 0 | 兩眼同步垂直移動 |
| `ParamEyeLOpen` | 左眼開閉 | 0 ～ 1 | 1 | 0=閉眼，1=全開 |
| `ParamEyeROpen` | 右眼開閉 | 0 ～ 1 | 1 | 眨眼動畫用 |
| `ParamBrowLY` | 左眉高度 | -1 ～ 1 | 0 | 負值=下壓，正值=抬高 |
| `ParamBrowRY` | 右眉高度 | -1 ～ 1 | 0 | 同上，右眉 |
| `ParamBrowLForm` | 左眉形狀 | -1 ～ 1 | 0 | 負值=皺眉，正值=驚訝弧 |
| `ParamBrowRForm` | 右眉形狀 | -1 ～ 1 | 0 | 同上，右眉 |
| `ParamMouthOpenY` | 嘴巴開合 | 0 ～ 1 | 0 | 0=閉嘴，1=全開（配音嘴型） |
| `ParamMouthForm` | 嘴型 | -1 ～ 1 | 0 | 負值=難過，正值=微笑 |
| `ParamBodyAngleX` | 身體左右傾斜 | -10 ～ 10 | 0 | 搖擺動畫 |
| `ParamBodyAngleY` | 身體前後傾斜 | -10 ～ 10 | 0 | |
| `ParamArmRAng` | 右手臂角度 | 0 ～ 1 | 0 | 0=放下，1=舉起揮手 |
| `ParamWingFlap` | 翅膀煽動 | 0 ～ 1 | 0 | 物理輸入驅動 |
| `ParamHairFront` | 前髮搖擺 | -1 ～ 1 | 0 | 物理輸入驅動 |
| `ParamHairBack` | 後髮搖擺 | -1 ～ 1 | 0 | 物理輸入驅動 |
| `ParamStar` | 星形髮夾搖擺 | -1 ～ 1 | 0 | 物理輸入驅動 |

### 4.2 關鍵形狀設定步驟

#### 眼球轉動（ParamEyeBallX / Y）

1. 在 `eye_L_iris` 和 `eye_L_pupil` 上設定形狀鍵
2. `ParamEyeBallX = -1`：虹膜向左移動約 15px（相對眼白寬度）
3. `ParamEyeBallX = 1`：虹膜向右移動約 15px
4. Y 軸同理（上 10px / 下 10px）
5. 在 `eye_L_white` 上設定同步輕微形變（眼白跟著微變）
6. 高光（`eye_L_highlight`）**不跟隨眼球移動**，保持固定位置

#### 頭部角度（ParamAngleX）

1. 選擇 `head_angle` 變形器
2. `ParamAngleX = -30`：臉左轉，左邊五官略壓縮，右邊拉伸，鼻子向左偏移
3. `ParamAngleX = 30`：反向，注意耳朵/側臉輪廓的形變要自然
4. 技巧：先設定 ±15 的中間形狀，讓插值更平滑

#### 嘴巴開合（ParamMouthOpenY）

1. `0`（閉嘴）：上下唇貼合，嘴角微彎（預設微笑）
2. `0.5`（半開）：顯示少量牙齒，用於輕聲說話
3. `1.0`（全開）：牙齒和舌頭完全可見，用於大笑/說話高峰

#### 眉毛表情（ParamBrowLY + ParamBrowRY + ParamBrowLForm）

組合設定目標表情：

| 表情 | BrowLY | BrowRY | BrowLForm | BrowRForm |
|------|--------|--------|-----------|-----------|
| 平靜 | 0 | 0 | 0 | 0 |
| 驚訝 | 0.8 | 0.8 | 0.5 | 0.5 |
| 困惑 | 0.3 | -0.3 | -0.3 | 0.3 |
| 思考 | -0.2 | 0.2 | -0.1 | 0 |
| 開心 | 0.2 | 0.2 | 0.3 | 0.3 |

---

## 5. 物理模擬設定

### 5.1 開啟物理設定

菜單：`模型` → `物理 / 場景混合設定`

### 5.2 各部位物理群組

#### A. 前髮（hair_bang_left / center / right）

```
物理群組名稱：前髮
輸入：
  - 類型：位置 X → 目標參數 ParamAngleX（倍率 0.3）
  - 類型：位置 Y → 目標參數 ParamAngleY（倍率 0.2）
輸出：
  - 目標：ParamHairFront（倍率 1.0）

擺錘設定（2段）：
  - 段 1（錨點）：長度 10，阻力 0.5，質量 0.3
  - 段 2（末端）：長度 20，阻力 0.8，質量 0.8
```

#### B. 後髮（hair_back_left / right）

```
物理群組名稱：後髮
輸入：ParamAngleX（倍率 0.4）
輸出：ParamHairBack（倍率 1.0）

擺錘設定（3段，比前髮更長更重）：
  - 段 1：長度 10，阻力 0.4，質量 0.2
  - 段 2：長度 25，阻力 0.6，質量 0.5
  - 段 3：長度 30，阻力 0.9，質量 1.0
```

#### C. 翅膀（四瓣各自獨立）

```
物理群組名稱：翅膀左上 / 左下 / 右上 / 右下
輸入：
  - ParamBodyAngleX（倍率 0.3）
  - 加入輕微呼吸模擬（使用正弦自動輸入）
輸出：ParamWingFlap（各翅膀獨立輸出）

擺錘設定（單段，輕盈感）：
  - 長度 25，阻力 0.3，質量 0.2
  - 重力 Y：0.1（讓翅膀有輕微下垂感）
```

#### D. 星形髮夾（star_hairpin）

```
物理群組名稱：星形髮夾
輸入：ParamAngleX（倍率 0.15，低靈敏）
輸出：ParamStar（倍率 0.5，小幅擺動）

擺錘設定（單段，偏硬）：
  - 長度 8，阻力 0.7，質量 0.1
  → 讓髮夾感覺是固體小掛飾，不要太飄
```

### 5.3 物理校調技巧

- **阻力（Damping）越高** → 靜止越快，適合較硬的物件（髮夾、翅膀主體）
- **質量（Mass）越大** → 慣性越強，適合較重的發束末端
- 開啟「物理播放」模式，移動畫布上的頭部變形器，實時觀察各部位搖擺是否自然
- 翅膀煽動頻率目標：每秒約 1.5～2 次（待機動畫中）

---

## 6. 表情設定

在 `expressions/` 目錄下建立以下 `.exp3.json` 檔：

### 6.1 需建立的表情文件

| 檔名 | 表情名稱 | 參數組合 |
|------|---------|---------|
| `exp_idle.exp3.json` | 平靜 | 全參數預設值 |
| `exp_happy.exp3.json` | 開心 | MouthForm=1, BrowLY=0.3, BrowRY=0.3 |
| `exp_thinking.exp3.json` | 思考 | EyeLOpen=0, EyeROpen=0, BrowLY=-0.2, MouthForm=-0.2 |
| `exp_speaking.exp3.json` | 說話 | MouthForm=0.5, BrowRY=0.4 |
| `exp_surprised.exp3.json` | 驚訝 | BrowLY=0.8, BrowRY=0.8, BrowLForm=0.5, MouthOpenY=0.3 |
| `exp_wink_L.exp3.json` | 左眼眨眼 | EyeLOpen=0 |
| `exp_wink_R.exp3.json` | 右眼眨眼 | EyeROpen=0 |

---

## 7. 動作錄製（4 個 Motion）

> 在 `motions/` 目錄下儲存，格式為 `.motion3.json`
> 建議在 30 FPS 下錄製

### 7.1 idle.motion3.json — 待機動畫

**時長**：6 秒（無縫循環）

| 時間 | 動作描述 | 關鍵參數 |
|------|---------|---------|
| 0s | 起始姿勢 | 全預設 |
| 1s | 輕微右傾 | AngleZ=3, BodyAngleX=2 |
| 2s | 眨眼 | EyeLOpen: 1→0→1（0.15s 完成） |
| 3s | 回正 | AngleZ=0, BodyAngleX=0 |
| 4s | 眼球微微向右看 | EyeBallX=0.3, EyeBallY=-0.1 |
| 5s | 輕微左傾 | AngleZ=-2, BodyAngleX=-1 |
| 6s | 回到起始（與 0s 相同） | 全預設 |

**技巧**：
- 整體動作幅度要小且緩慢（Ease In/Out 緩動）
- 約 3秒 自動眨眼一次
- 翅膀依賴物理引擎自動搖擺，不需要手動設置關鍵幀

### 7.2 thinking.motion3.json — 思考動畫

**時長**：4 秒（可循環）
**參考圖**：`reference/thinking.png`

| 時間 | 動作描述 | 關鍵參數 |
|------|---------|---------|
| 0s | 起始（開眼） | 全預設 |
| 0.5s | 緩慢閉眼、頭微低 | EyeLOpen: 1→0, EyeROpen: 1→0, AngleY=-5 |
| 1s | 思考表情定格 | BrowLY=-0.2, BrowLForm=-0.1, MouthForm=-0.1 |
| 2.5s | 保持思考 | （維持參數，翅膀仍搖擺） |
| 3.5s | 緩慢回正（睜眼） | EyeLOpen: 0→1, EyeROpen: 0→1, AngleY=0 |
| 4s | 回到起始 | 全預設 |

### 7.3 speaking.motion3.json — 說話動畫

**時長**：3 秒（可循環，搭配語音嘴型系統使用）
**參考圖**：`reference/speaking.png`

| 時間 | 動作描述 | 關鍵參數 |
|------|---------|---------|
| 0s | 開始說話 | MouthOpenY: 0→0.6 |
| 0.2s | 半閉 | MouthOpenY: 0.6→0.2 |
| 0.5s | 再開 | MouthOpenY: 0.2→0.7 |
| 1s | 微閉 | MouthOpenY: 0.7→0.1 |
| 1.5s | 手指微動 | （右手臂輕微抖動，ParamArmRAng: 0.5→0.6→0.5） |
| 3s | 回到起始 | MouthOpenY=0 |

**注意**：實際口型同步（Lip Sync）由 Cubism SDK 的 CubismLipSync 驅動，此動作僅作為基底動畫使用。

### 7.4 wave.motion3.json — 揮手動畫

**時長**：5 秒（建議播放一次，不循環）
**參考圖**：`reference/wave.png`

| 時間 | 動作描述 | 關鍵參數 |
|------|---------|---------|
| 0s | 起始姿勢 | 全預設 |
| 0.3s | 身體前傾、右手舉起 | BodyAngleY=-3, ArmRAng: 0→0.8 |
| 0.6s | 第一次揮手 | ArmRAng: 0.8→1.0 |
| 1.0s | 揮回 | ArmRAng: 1.0→0.7 |
| 1.4s | 第二次揮手 | ArmRAng: 0.7→1.0 |
| 1.8s | 揮回 | ArmRAng: 1.0→0.7 |
| 2.2s | 第三次揮手（最高） | ArmRAng: 0.7→1.0, AngleZ=5 |
| 3.0s | 緩慢放下手 | ArmRAng: 1.0→0 |
| 3.5s | 身體回正 | BodyAngleY=0, AngleZ=0 |
| 5s | 回到起始 | 全預設 |

**搭配表情**：揮手期間觸發 `exp_happy`，手放下後返回 `exp_idle`

---

## 8. 匯出清單

### 8.1 匯出步驟

1. 菜單：`文件` → `嵌入紋理輸出` → 選擇 `models/fairy/` 目錄
2. 確認所有紋理圖集已正確打包至 `textures/` 目錄
3. 菜單：`文件` → `輸出運行時文件`

### 8.2 必要輸出檔案清單

```
models/fairy/
├── fairy.moc3              ← 主要模型二進位（Cubism SDK 讀取）
├── fairy.model3.json       ← 模型定義（指向 moc3、紋理、動作、物理）
├── fairy.physics3.json     ← 物理設定
├── fairy.pose3.json        ← 姿勢設定（若有使用）
├── fairy.cdi3.json         ← 參數/部件顯示資訊（Cubism Viewer 用）
│
├── textures/
│   ├── fairy.4096.png      ← 主要紋理圖集（建議 4096×4096 或 2048×2048×2）
│   └── fairy.4096_1.png    ← 若圖層過多，Cubism 會自動分割
│
├── motions/
│   ├── idle.motion3.json
│   ├── thinking.motion3.json
│   ├── speaking.motion3.json
│   └── wave.motion3.json
│
└── expressions/
    ├── exp_idle.exp3.json
    ├── exp_happy.exp3.json
    ├── exp_thinking.exp3.json
    ├── exp_speaking.exp3.json
    ├── exp_surprised.exp3.json
    ├── exp_wink_L.exp3.json
    └── exp_wink_R.exp3.json
```

### 8.3 `fairy.model3.json` 結構範例

```json
{
  "Version": 3,
  "FileReferences": {
    "Moc": "fairy.moc3",
    "Textures": [
      "textures/fairy.4096.png"
    ],
    "Physics": "fairy.physics3.json",
    "Expressions": [
      { "Name": "idle",      "File": "expressions/exp_idle.exp3.json" },
      { "Name": "happy",     "File": "expressions/exp_happy.exp3.json" },
      { "Name": "thinking",  "File": "expressions/exp_thinking.exp3.json" },
      { "Name": "speaking",  "File": "expressions/exp_speaking.exp3.json" },
      { "Name": "surprised", "File": "expressions/exp_surprised.exp3.json" },
      { "Name": "wink_L",    "File": "expressions/exp_wink_L.exp3.json" },
      { "Name": "wink_R",    "File": "expressions/exp_wink_R.exp3.json" }
    ],
    "Motions": {
      "Idle":     [{ "File": "motions/idle.motion3.json",     "FadeInTime": 0.5, "FadeOutTime": 0.5 }],
      "Thinking": [{ "File": "motions/thinking.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5 }],
      "Speaking": [{ "File": "motions/speaking.motion3.json", "FadeInTime": 0.3, "FadeOutTime": 0.3 }],
      "Wave":     [{ "File": "motions/wave.motion3.json",     "FadeInTime": 0.5, "FadeOutTime": 0.8 }]
    }
  },
  "Groups": [
    { "Target": "Parameter", "Name": "EyeBlink",    "Ids": ["ParamEyeLOpen", "ParamEyeROpen"] },
    { "Target": "Parameter", "Name": "LipSync",     "Ids": ["ParamMouthOpenY"] }
  ]
}
```

### 8.4 匯出後驗證

- [ ] 在 Cubism Viewer for OW（官方 Web Viewer）載入 `fairy.model3.json`，確認模型正常顯示
- [ ] 逐一播放 4 個動作，確認無穿模或異常形變
- [ ] 移動「面部追蹤」測試滑桿，確認頭部轉動、眼球移動流暢
- [ ] 測試物理：快速拖拽頭部後放開，頭髮/翅膀/髮夾應有自然殘影搖擺
- [ ] 在 Chrome DevTools 中載入 pixi-live2d-display 並執行，確認 WebGL 渲染正常

---

## 9. 目錄結構規範

```
libs/live2d-core/
├── models/
│   └── fairy/                  ← 主角色（仙子）
│       ├── MODELING_GUIDE.md   ← 本文件
│       ├── reference/          ← 原始參考圖（不打包進發布版）
│       │   ├── idle.png
│       │   ├── thinking.png
│       │   ├── speaking.png
│       │   └── wave.png
│       ├── textures/           ← 紋理圖集（匯出後填入）
│       ├── motions/            ← 動作文件（匯出後填入）
│       ├── expressions/        ← 表情文件（匯出後填入）
│       ├── fairy.moc3          ← 待建模後匯出
│       ├── fairy.model3.json   ← 待建模後匯出
│       ├── fairy.physics3.json ← 待建模後匯出
│       └── fairy.cdi3.json     ← 待建模後匯出
│
└── src/                        ← TypeScript SDK 整合（Phase 1 建立）
    ├── Live2DManager.ts
    ├── AIAssistantWidget.tsx
    └── ...
```

---

## 附錄：建模工作流程時間估算

| 階段 | 工作內容 | 預估工時 |
|------|---------|---------|
| PSD 拆層 | Photoshop 手動繪製各圖層 | 6～10 小時 |
| 網格設定 | Cubism 自動網格 + 手動調整關鍵部位 | 2～4 小時 |
| 參數設定 | 各參數形狀鍵 × 19 個參數 | 8～12 小時 |
| 物理設定 | 4 個物理群組調校 | 2～3 小時 |
| 動作錄製 | 4 個動作 × 30FPS | 4～6 小時 |
| 表情設定 | 7 個表情文件 | 1～2 小時 |
| 測試調整 | Viewer 驗證 + 修正 | 2～4 小時 |
| **總計** | | **25～41 小時** |

> 建議優先完成「眼睛、嘴巴、頭部角度」三大核心參數，再推進至肢體動作。
> 物理模擬可以在核心參數完成後才設定，不影響前期進度。
