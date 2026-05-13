# HANDOFF · tmux-as-bridge video tutorial (3/10 完成 + 已上線)

**timestamp**: 2026-05-12 00:14
**previous session**: cannibalize ConardLi/garden-skills → web-video-tutorial skill → dogfood test
**workdir**: `~/workshop/outputs/video-tutorial/tmux-as-bridge/`

---

## Goal

用 web-video-tutorial skill（剛蠶食完成的）把少爺 blog 文章
`https://blog.joneshong.com/zh/blog/tmux-as-bridge` 做成 16:9 點擊驅動網頁影片。
完成第 1-3 章 + TTS + 1.4x 加速 + nginx PUBLIC 掛載 + App Launcher 按鈕。
剩 7 章（4-10）待做，已有 outline + 素材 + 工具鏈，後續可直接接續。

---

## Key Decisions

1. **主題：terminal-green** —— CLI tutorial 完美命中 `bestFor: ["CLI 工具教程", "命令行實操", "復古技術致敬"]`
2. **開發模式：A 逐章確認** —— 每章主執行緒做完暫停驗收（不並行）
3. **素材：從 blog 自動下載** —— 13 張 png 進 `presentation/public/assets/`
4. **TTS：Workshop tts station + edge engine + zh-CN-YunxiNeural** —— port 10201，9 引擎可換
5. **音頻 1.4x 加速** —— ffmpeg `atempo=1.4` in-place，總時長 109s → 78s，順帶解掉 statusline/3 >15s 預警
6. **Nginx：PUBLIC no-auth + alias 直 serve dist/** —— 仿 `/apps/five-layer/` pattern
7. **App entry color：磷光綠 #41ff97** —— 對齊 terminal-green accent，icon 用 📼
8. **STORAGE_KEY bump：v4 → v6** —— 每加章節要 bump（目前 v6，3 章）

---

## Files

### 新建（這次製作）
- `outputs/video-tutorial/tmux-as-bridge/article.md` — 8.3KB blog 原文（雙源原則）
- `outputs/video-tutorial/tmux-as-bridge/script.md` — 4.3KB 口播稿（過 SCRIPT-STYLE 三層自檢）
- `outputs/video-tutorial/tmux-as-bridge/outline.md` — 10 章 / 50 步 + 信息池 + 素材清單
- `outputs/video-tutorial/tmux-as-bridge/presentation/` — Vite + React + TS scaffold
  - `src/chapters/01-coldopen/` (3 step) · `02-origin/` (5 step) · `03-statusline/` (5 step)
  - `public/assets/*.png` (13 張 blog 截圖)
  - `public/audio/*/*.mp3` (13 段 TTS @ 1.4x)
  - `dist/` (production build, nginx 直 serve)

### 修改
- `workbench/src/shared/constants/apps.ts` — 加 `tmux-as-bridge` entry
- `workbench/dist/` — pnpm build 完成
- `/opt/homebrew/etc/nginx/conf.d/workshop-apps.inc` — 加 PUBLIC location（line 14 之後）
- `vite.config.ts` — base `/apps/tmux-as-bridge/`
- `hooks/useStepper.ts` — STORAGE_KEY v6

### 驗證 URL
- https://workshop.joneshong.com/ → App Launcher 找 📼 tmux as bridge
- https://workshop.joneshong.com/apps/tmux-as-bridge/ → HTTP 200
- https://workshop.joneshong.com/apps/tmux-as-bridge/?auto=1 → 一鏡到底（按 SPACE 啟動）

---

## Next Steps

### 接續做 ch 4-10（按 outline.md）

| ch | id | steps | 預計時長 | 自帶素材 |
|----|-----|-------|---------|---------|
| 4 | layouts | 5 | ~38s | layout-4col/cross/main-subs.png ✓ |
| 5 | remote-tmux | 5 | ~32s | 無（純 CSS terminal demo）|
| 6 | cross-device | 6 | ~46s | webui-overview/skill-palette/agent-live.png ✓ |
| 7 | why-multi-agent | 6 | ~44s | 無（5 個理由純文字 + 視覺）|
| 8 | how-multi-agent | 7 | ~52s | 無 |
| 9 | handoff-and-qa | 5 | ~38s | qa-1~6.png ✓ |
| 10 | closing | 3 | ~22s | 無 |

### 每章標準流程
1. `mkdir presentation/src/chapters/NN-<id>/` + 寫 Tsx + Css + narrations.ts
2. Edit `registry/chapters.ts` 註冊
3. bump `useStepper.ts` STORAGE_KEY v6 → v7 → ...
4. `npx tsc --noEmit` 過
5. 驗收後合成新音頻：
   ```bash
   cd presentation
   npm run extract-narrations    # incremental
   bash scripts/synthesize-audio.sh --voice=zh-CN-YunxiNeural  # skip-existing
   # 對新檔跑 1.4x：for f in public/audio/<new-ch>/*.mp3; do ffmpeg ... atempo=1.4; done
   ```
6. `npm run build` → nginx 立即反映（不需 reload）

### 可選優化
- `scaffold.sh` line 187 unbound variable bug
- `synthesize-audio.sh` 加 `--speed=1.4` flag（避免手動 ffmpeg）
- `statusline/3` step 2 narration 偏密（1.4x 後 11.8s 通過但塞 5 想法），可考慮拆 step

---

## Risks / Watch-outs

1. **動畫預算邊界**：coldopen step 0/1 typing 動畫餘裕只 0.5s。若實測太急，縮 typing 1300ms → 1000ms（`Coldopen.css` `.co-typed-1/2` animation duration）
2. **edge 中文音色**：少爺尚未確認試聽結果。不滿意可換 `--engine=kokoro` 或 `qwen3-tts` 重合成
3. **STORAGE_KEY bump 義務**：每加 chapter 必 bump，否則舊瀏覽器 cursor 落不存在 step
4. **App Launcher cache**：改 apps.ts 必 workbench rebuild（~30s），瀏覽器 hard refresh 才看到
5. **dev server 5174 與 nginx 獨立**：nginx serve `dist/`，停掉 npm dev 不影響線上版
6. **nginx config line 495 既有 warning**：duplicate MIME type `text/html`，與本次無關，但建議清
7. **這個 dist 不會自動 rebuild**：少爺改 source 後要 `npm run build` 才會反映到 nginx serve

---

## Verification Passed

- ✓ 13/13 mp3 合成成功 + 1.4x 加速完成
- ✓ Vite build asset path 正確（`/apps/tmux-as-bridge/assets/...`）
- ✓ Nginx -t pass + reload，URL HTTP 200 全綠
- ✓ App Launcher entry bundled 進 workbench
- ✓ `npx tsc --noEmit` 全章節過
- ✓ script.md 三層自檢 / outline.md 自檢全過（reviewer agent 確認）

---

## Skill 蠶食關聯（補充）

這是 web-video-tutorial skill（剛從 ConardLi/garden-skills 蠶食）的**第一次完整端到端 dogfood**。驗證了：
- (chapter, step) cursor model 在實戰 work
- narrations.ts 單一真相源機制有效
- Workshop tts station 接入正確（蠶食時 mmx → tts station 改寫成功）
- 雙源原則 + terminal-green token + 反 AI 味五類 落地容易

蠶食原 intelflow report id: `019e172a0d167552abe3ee37a9a27f41`
