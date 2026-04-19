# auto-survey Rust 化 — HANDOFF

給下游 phase agent 讀，避免重看 Python 源碼。

**目標 worktree**: `.worktrees/feature/auto-survey-rs`
**原 Python 碼**: `stations/auto-survey/`（只讀參考，不動）
**新 Rust 碼（將建立）**: `stations/auto-survey-rs/`

---

## 1. 檔案樹 + 職責

| 檔案 | 行數 | 職責 | Rust 移植策略 |
|---|---|---|---|
| `src/auto_survey/__init__.py` | 3 | Package marker | — |
| `src/auto_survey/__main__.py` | 5 | `python -m auto_survey` entry | cli binary |
| `src/auto_survey/config.py` | 35 | `pydantic-settings` (env `AUTO_SURVEY_*`) | `serde` + env var |
| `src/auto_survey/models.py` | 108 | SQLAlchemy ORM — Survey/Question/Person/Submission/DailyRun | `sqlx::FromRow` structs |
| `src/auto_survey/db.py` | 25 | `sessionmaker(engine)` | `sqlx::Pool<Sqlite>` |
| `src/auto_survey/analyzer.py` | 382 | LiteLLM call + retry + `analyze_quiz/quiz_rlm/reanalyze_wrong` | `reqwest` + retry loop |
| `src/auto_survey/pw.py` | 500 | `BrowserSession` abstraction + Camoufox/Playwright CLI wrappers | `tokio::process::Command` |
| `src/auto_survey/recon.py` | 178 | Phase 1: 透過 pw 偵測 survey 結構、分類 subjects | Rust port |
| `src/auto_survey/filler.py` | 278 | Phase 3: 填單 + submit + 抓分數 | Rust port |
| `src/auto_survey/orchestrator.py` | 257 | Pipeline: recon → analyze → fill + retry | Rust port |
| `src/auto_survey/web.py` | 571 | FastAPI routes + static + CORS | `axum` |
| `src/auto_survey/notify.py` | 33 | Bark push（curl subprocess） | `reqwest` |
| `src/auto_survey/cli.py` | 402 | Click CLI — import people、run、serve 等 | `clap` |
| `src/auto_survey/line_reader.py` | 473 | **macOS Vision OCR + AppleScript 抓 LINE 訊息** | **保留 Python**（詳見 §9） |
| `store.py`（station root） | 134 | Reactive store — 事件發送給 `stations/agent-vista` | 可選（不阻塞）|

---

## 2. DB Schema（完整）

Namespace: `auto_survey` schema（PostgreSQL）→ 遷移後 SQLite file `data/auto_survey.db`

### `surveys`
| 欄位 | 型別 | 備註 |
|---|---|---|
| id | UUID PK | `gen_random_uuid()` |
| url | TEXT NOT NULL | |
| url_hash | TEXT NOT NULL UNIQUE | SHA-256 of URL |
| title | TEXT | 從 survey 頁面抓 |
| type | TEXT NOT NULL | `attendance` \| `quiz` |
| raw_content | TEXT | 原始頁面 snapshot |
| company_options | JSONB | `list[str]` |
| created_at | TIMESTAMPTZ | |

### `questions`
| 欄位 | 型別 | 備註 |
|---|---|---|
| id | UUID PK | |
| survey_id | UUID FK → surveys(id) ON DELETE CASCADE | |
| subject_id | TEXT NOT NULL | SurveyCake 的 subject slug（如 `subject-5`）|
| question_text | TEXT NOT NULL | |
| options | JSONB NOT NULL | `list[str]` |
| correct_answer | TEXT | LLM 回答，可空 |
| verified | BOOL NOT NULL DEFAULT false | pathfinder 驗證後才 true |
| created_at | TIMESTAMPTZ | |

### `people`
| 欄位 | 型別 | 備註 |
|---|---|---|
| id | UUID PK | |
| name | TEXT NOT NULL | |
| email | TEXT NOT NULL UNIQUE | |
| company | TEXT NOT NULL | 對應 `Survey.company_options` 中的值 |
| active | BOOL NOT NULL DEFAULT true | |
| created_at | TIMESTAMPTZ | |

### `submissions`
| 欄位 | 型別 | 備註 |
|---|---|---|
| id | UUID PK | |
| survey_id | UUID FK → surveys(id) | CASCADE |
| person_id | UUID FK → people(id) | CASCADE |
| status | TEXT CHECK IN (success, failed, skipped) | |
| score | INTEGER | quiz 分數；attendance 為 null |
| is_pathfinder | BOOL DEFAULT false | 本輪 pathfinder（Python 裡有，SQL migration 沒列，要補）|
| answers_snapshot | JSONB | `{subject_id: answer_text}`（SQL migration 沒列，要補）|
| error_message | TEXT | |
| submitted_at | TIMESTAMPTZ | |
| CONSTRAINT uq_survey_person UNIQUE (survey_id, person_id) | | |

**索引**:
- `idx_submissions_survey (survey_id)`
- `idx_submissions_person (person_id)`
- `idx_questions_survey (survey_id)`

### `daily_runs`（新增，SQL migration 也缺）
| 欄位 | 型別 | 備註 |
|---|---|---|
| id | UUID PK | |
| run_date | DATE NOT NULL UNIQUE | |
| attend_url | TEXT | |
| quiz_url | TEXT | |
| status | TEXT DEFAULT 'pending' | pending / running / completed / failed |
| result_summary | TEXT | |
| created_at / updated_at | TIMESTAMPTZ | |

### PG → SQLite 型別對應
| PG | SQLite |
|---|---|
| UUID | TEXT（lowercase hex，無破折號亦可）|
| JSONB | TEXT（JSON 字串）|
| TIMESTAMPTZ | TEXT（ISO-8601 含 offset）|
| DATE | TEXT（`YYYY-MM-DD`）|
| BOOLEAN | INTEGER（0/1）|
| INTEGER | INTEGER |
| TEXT | TEXT |

**特別注意**：Python migration 001_init.sql 缺 `is_pathfinder` 和 `answers_snapshot`（ORM 有但 SQL 沒有）。Phase 2 的 SQLite migration 要**補齊**，遷移腳本也要處理這兩欄（若 PG 實際已有欄位就讀，沒有就 default）。

---

## 3. 外部整合

### 3.1 LiteLLM（analyzer.py）
- **Endpoint**: `http://localhost:4000/v1/chat/completions`（由 `AUTO_SURVEY_LITELLM_BASE_URL` 覆蓋）
- **Model**: `grok-4.1-fast`（由 `AUTO_SURVEY_LLM_MODEL` 覆蓋）
- **API key**: `sk-litellm-local-dev`（本地，非真金鑰）
- **格式**: OpenAI chat completions，純 JSON 回應（**無 `response_format`**，靠 prompt 要求）
- **Retry**: 5 次重試，針對 transient errors（BrokenPipeError / APIConnectionError / APITimeoutError / OSError errno 32 等）；每次重試**用全新 client**（避免 stale keepalive）
- **Backoff**: 未明確指定，讓下游重寫時補上（建議 exponential 1/2/4/8s）

### 3.2 Prompt 原文（**Rust 逐字保留，絕不改寫**）

#### `_build_prompt(questions)` — quiz 基本分析
```
你是測驗分析專家。以下是線上測驗的選擇題。
請分析每題的正確答案，只回傳選項字母（A/B/C/D）。

以純 JSON 格式回答（不要 markdown code fence）：
{"answers": [{"subject_id": "subject-5", "answer": "C"}, ...]}

題目：

subject-5: <question_text>
  A. <option1>
  B. <option2>
  ...
```

#### `analyze_quiz_rlm` — 強化版（RLM engine）
待 Phase 3a agent 讀 `analyzer.py` line 243-350 節錄。結構類似但加 reasoning trace。

#### `reanalyze_wrong` — pathfinder < 100 分時重答
讀 `analyzer.py` line 347+。

**Rust 端**: 把 prompt 放在 `src/analyzer.rs` 裡當 `const`，**用 `r#"..."#` raw string**保持字面一致。

### 3.3 Camoufox / Playwright CLI（pw.py）

介面（`BrowserSession` abstract class）：
- `open(url) → str`
- `navigate(url) → str`
- `run_code(js, timeout=60) → str`
- `snapshot(interactive=True) → str` — 回 JSON 包含 `@elN` refs
- `click(ref) → str`
- `fill(ref, text) → str`
- `screenshot(full_page=False) → str`
- `close() → str`

**Camoufox 呼叫模式**（外部網站，如 SurveyCake）：
```bash
camoufox-cli --session <sid> --headed --persistent ~/.camoufox-profiles/master open <url>
camoufox-cli --session <sid> snapshot -i        # 互動 JSON
camoufox-cli --session <sid> click "@el3"
camoufox-cli --session <sid> fill "@el5" "text"
camoufox-cli --session <sid> close
```

**Session ID**: `uuid.uuid4().hex[:8]`，在 Rust 端用 `uuid::Uuid::new_v4().simple().to_string()[..8]`。

**Playwright 為備援**（`playwright-cli --profile $PW_PROFILE -s=<sid>-001 ...`），JS 格式不同（async 函式包裝）— 本次 Rust 版**先只實作 Camoufox**，playwright fallback 列入 follow-up。

### 3.4 Bark Notify
```
GET {bark_server}/{device_key}/{urlencoded_title}/{urlencoded_body}
```
預設：`http://localhost:8090/gx7KnK5f8iAKuqNLWzy5hP/.../...`

Rust 端：`reqwest::Client::get(...).send()` + 檢查 `{"code": 200}`。

### 3.5 LINE OCR（line_reader.py）— **方案 C：100% Rust**

**動作鏈**（macOS-only，全由 Rust subprocess 驅動）：
1. **osascript**：`tell application "LINE" to activate` → 點社群 / scroll up
2. **Quartz（core-graphics crate）**：`CGWindowListCopyWindowInfo` 抓 LINE CGWindowID
3. **screencapture -l <wid>**：截圖（subprocess）
4. **sips --cropToHeightWidth**：裁切右側訊息區（subprocess）
5. **HTTP POST `http://127.0.0.1:10202/extract?engine=apple&languages=zh-Hant,zh-Hans,en&path=<png>`**
   - 呼叫 **workshop 自家的 `stations/ocr` service**（port 10202）
   - 底層是 `stations/ocr/bin/apple-ocr` Swift binary（已脫離 pyobjc，純 Swift Vision.framework）
   - reqwest GET 返回 `{"text": "...", "engine": "apple", ...}`
6. **regex**（`regex` crate）：`r"https?://w{2,3}\.surveycake\.com/s/\w+"`

**Rust 端要做**:
- `osascript -e '<applescript>'` 執行 AppleScript（`_SCRIPT_ACTIVATE` / `_SCRIPT_ESCAPE` / `_SCRIPT_SCROLL_UP` 三段原文**逐字保留**）
- 用 `core-graphics` crate 或 `tauri-plugin-process` 取 CGWindowID（若 crate 不順，也可 subprocess + awk 從 `mdls` / 自寫 swift 小工具）
- subprocess chain：`screencapture` → `sips` → HTTP OCR → regex

**Rust 化困難度：中低**（全靠 subprocess + 1 個 HTTP 呼叫，無需 Vision FFI）。

---

## 4. 環境變數

`pydantic-settings` 讀 `AUTO_SURVEY_*` 前綴。配置：

| env | default | 說明 |
|---|---|---|
| `AUTO_SURVEY_DATABASE_URL` | `postgresql://joneshong:REDACTED@127.0.0.1/workshop` | **Rust 版改 SQLite，此變數棄用，改 `AUTO_SURVEY_SQLITE_PATH`** |
| `AUTO_SURVEY_SCHEMA_NAME` | `auto_survey` | SQLite 不用 |
| `AUTO_SURVEY_LLM_BACKEND` | `litellm` | `litellm`/`gemini`/`claude`/`codex` |
| `AUTO_SURVEY_LLM_MODEL` | `grok-4.1-fast` | |
| `AUTO_SURVEY_LITELLM_BASE_URL` | `http://localhost:4000/v1` | |
| `AUTO_SURVEY_LITELLM_API_KEY` | `sk-litellm-local-dev` | |
| `AUTO_SURVEY_MIN_DELAY` / `MAX_DELAY` | `5` / `15` | 秒，filler 間隔 |
| `AUTO_SURVEY_HEADLESS` | `true` | |
| `AUTO_SURVEY_CAMOUFOX_CLI` | `camoufox-cli` | PATH 可見 |
| `AUTO_SURVEY_CAMOUFOX_PROFILE` | `~/.camoufox-profiles/master` | |
| `AUTO_SURVEY_PLAYWRIGHT_CLI` | `playwright-cli` | fallback |
| `AUTO_SURVEY_PW_PROFILE_DIR` | `""` | empty → temp APFS clone |
| `AUTO_SURVEY_EXECUTION_HOUR` | `14` | 小於此時間 → scheduled，大於 → 立即執行 |
| `AUTO_SURVEY_WEB_PORT` | `10300` | |
| `AUTO_SURVEY_BARK_DEVICE_KEY` | `gx7KnK5f8iAKuqNLWzy5hP` | |
| `AUTO_SURVEY_BARK_SERVER` | `http://localhost:8090` | |
| `AUTO_SURVEY_LINE_COMMUNITY_NAME` | `微光早餐會` | |
| `AUTO_SURVEY_LINE_ENABLED` | `true` | |
| `AUTO_SURVEY_LINE_SCROLL_PAGES` | `3` | |

---

## 5. Static / CSV 格式

### `people.csv`（import 用）
欄位順序（見 `cli.py` import 指令）：
```csv
name,email,company
張三,zhang@example.com,A公司
李四,li@example.com,B公司
```

### `static/`
SurveyCake 偵錯頁 + 簡單 admin UI。Rust 版用 `tower-http::services::ServeDir` 直接服務即可。

---

## 6. Cronicle 排程

**現況**（`schedules/manifest.json`）：
```json
{
  "name": "ws-auto-survey-wed",
  "label": "com.joneshong.scheduler.ws-auto-survey-wed",
  "command": "~/.local/bin/python3 ~/workshop/schedules/runners/ws_auto_survey.py",
  "schedule": { "calendar": { "Weekday": 3, "Hour": 13, "Minute": 0 } }
},
{
  "name": "ws-auto-survey-fri",
  ...
  "schedule": { "calendar": { "Weekday": 5, "Hour": 13, "Minute": 0 } }
}
```

該 runner（`ws_auto_survey.py`）做：呼叫 LINE OCR → 取 URL → HTTP POST 給 auto-survey web :10300 / (或 CLI 執行 orchestrator)。

**Phase 4 要做**：
1. **新增 2 job**：`ws-auto-survey-start`（週三/五 10:00 `launchctl kickstart`）+ `ws-auto-survey-stop`（週三/五 18:00 `launchctl kill`）
2. **改現有 `ws-auto-survey-wed/fri`**：13:00 的 runner 改成 HTTP POST 給 `:10300/api/run`（因為 10:00 後服務應該已在）
3. **新 launchd plist** `com.workshop.auto-survey-rs.plist`：`RunAtLoad=false`, `KeepAlive=false`

---

## 7. 不可漏掉的 Quirks

1. **is_pathfinder + answers_snapshot**：ORM 有但 `migrations/001_init.sql` 缺。**Phase 2 SQLite migration 必補**
2. **Prompt 全繁體中文 + 要求純 JSON 無 markdown fence**。Rust 端要保留這個指令
3. **Retry transient errors 的分類清單**（analyzer.py line 18-32）— 至少要複現：BrokenPipeError, OSError errno 32, ConnectionError, APIConnectionError, APITimeoutError, InternalServerError 等
4. **Pathfinder 先跑、< 100 分則 `reanalyze_wrong`**：pipeline 關鍵節點（orchestrator.py line 170-200）
5. **人員 shuffle**：`random.shuffle(people)` 後第一個當 pathfinder（orchestrator.py line 157）
6. **交錯延遲**：填下一人前 `random.randint(min_delay, max_delay)` 秒（orchestrator.py line 227）
7. **已成功 submission 跳過**：orchestrator.py line 215-224 用 SQL 判斷 `status='success'` 直接 skip
8. **Survey upsert by url_hash**：recon.py `save_survey()` 檢查 `url_hash`，避免重複建立
9. **store.py dispatch**：fire-and-forget 給 agent-vista。**Rust 版可以先不實作**（best-effort，try/except pass）

---

## 8. 給下游 Phase Agent 的建議

### 容易翻（低風險）
- **Phase 3a analyzer**：純 HTTP client + JSON parse，retry 邏輯直譯。**Prompt 逐字保留**
- **Phase 3d notify**：Bark 就是 GET URL，30 行 Rust 搞定
- **Phase 3b web**：axum routes 直翻 FastAPI endpoint 清單

### 要小心（中風險）
- **Phase 2 資料遷移**：PG UUID → SQLite TEXT 要統一格式（建議全部 lowercase hex，無破折號）；JSONB → TEXT 注意空值 `null` vs `"null"` vs `""`
- **Phase 3c orchestrator**：有狀態機 + retry + pathfinder 分支，逐行對照 Python 版寫測試
- **Phase 3c filler**：Python 版在 filler.py 有填單順序、等待策略、分數抓取邏輯，這些行為要保持一致

### 高風險
- 無（原先 line_reader.py 已改方案 C 降為中低風險）

---

## 9. ✅ 設計決策（少爺已拍板：方案 C）

**line_reader Rust 化策略**：100% Rust，OCR 外包給自家服務。

### Rust 實作分工
| 步驟 | Rust 端 | 外部 |
|---|---|---|
| AppleScript 操作 LINE | `Command::new("osascript").arg("-e")` | — |
| 取 LINE CGWindowID | `core-graphics` crate（或 subprocess + plist 解析）| — |
| 截圖 | `Command::new("screencapture")` | — |
| 裁切 | `Command::new("sips")` | — |
| **OCR** | `reqwest::get("http://127.0.0.1:10202/extract?...")` | **stations/ocr :10202**（Apple Vision Swift binary）|
| URL regex | `regex::Regex` | — |

### 記憶體帳
| 元件 | RSS | 在線時段 |
|---|---|---|
| auto-survey-rs（server + line reader all-in-one） | ~12 MB | 週三/五 10:00-18:00 |
| stations/ocr（apple engine） | 25-30 MB | lazy-load（目前常駐，未來可按需 wake）|

### 為什麼 C 比 A'/B 好
- **A（整包 Python sidecar）**：保留 473 行 Python，違反 Rust 化目標
- **A'（只留 OCR Python helper）**：還是要維護 Python 腳本
- **B（手刻 Vision FFI）**：+3-5 天工時，Rust Vision 綁定粗糙
- **C（委派 ocr station）**：0 天額外工時，0 Python 殘留，OCR 能力跟原版 1:1（同一個 Apple Vision 底層）

### Phase 3d 範圍（已擴增）
原只含 LINE reader + Bark notify；現含：
- LINE 操控（osascript chain）
- 截圖 + 裁切（screencapture + sips）
- OCR HTTP 呼叫（localhost:10202）
- SurveyCake URL regex
- Bark notify HTTP

---

**HANDOFF 完成，交給 Phase 1 agent 開工。**
