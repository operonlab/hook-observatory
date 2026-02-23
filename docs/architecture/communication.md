---
doc_version: 1
content_hash: b6f7fdd7
source_version: 1
target_lang: zh-TW
translated_at: 2026-02-23
---

# 通訊模式 (Communication Patterns)

## 概覽

```
┌──────────────────────────────────────────────────────────┐
│  Browser (Single React App)                              │
│                                                          │
│  HTTP/SSE ──────────┐           WebRTC ──────────┐       │
└─────────────────────┼───────────────────────────┼───────┘
                      ▼                           ▼
              ┌──────────────┐           ┌──────────────┐
              │   Nginx      │           │   LiveKit     │
              │   Gateway    │           │   Server      │
              └──────┬───────┘           └──────┬───────┘
                     │                          │
                     ▼                          ▼
        ┌────────────────────────┐     ┌──────────────┐
        │    Core Monolith       │     │   Realtime    │
        │   ┌──────┬──────┐     │     │   Agents      │
        │   │auth  │quest │     │     └──────┬───────┘
        │   ├──────┼──────┤     │            │
        │   │finance│muse │     │     ┌──────┴───────┐
        │   └──────┴──────┘     │     │    Media      │
        │         │             │     │  (STT/TTS)    │
        │    Event Bus          │     └──────────────┘
        └───────┬───────────────┘
                │
          ┌─────┴─────┐
          │   Redis   │ (Cache + Events)
          └─────┬─────┘
                │
          ┌─────┴─────┐
          │ PostgreSQL│ (Per-schema)
          └───────────┘
```

## 1. Frontend → Backend: HTTP + Streaming

### 標準 Request/Response

所有前端到後端的通訊均透過 Nginx 反向代理至 Core Monolith，並使用 **HTTP REST**。

```
Browser → https://domain.com/api/finance/transactions → Nginx → Core Monolith
```

**慣例**:
- `GET` 用於讀取，`POST` 用於建立，`PUT` 用於完整更新，`PATCH` 用於部分更新，`DELETE` 用於刪除
- Request/response body 使用 JSON 格式（鍵名採用 camelCase 以相容 JS）
- 分頁：使用 `?page=1&limit=20` 搭配 `X-Total-Count` 標頭
- 錯誤處理：使用 `{ "detail": "message" }` 搭配適當的 HTTP 狀態碼

### 串流 (SSE)

針對執行時間較長的作業或 LLM 回應，使用 **Server-Sent Events**:

```
Browser → GET /api/chat/stream (Accept: text/event-stream) → Nginx → Core
         ← data: {"chunk": "Hello"}\n\n
         ← data: {"chunk": " world"}\n\n
         ← data: [DONE]\n\n
```

**何時使用 SSE 與 WebSocket:**

| 標準 | SSE | WebSocket |
|----------|-----|-----------|
| 方向 | Server → Client (單向) | 雙向 |
| 使用場景 | LLM 串流、進度更新 | 聊天、即時協作 |
| 重新連接 | 內建自動重連 | 需手動實作 |
| 透過代理 | 可直接透過 Nginx/CDN | 需 `Upgrade` 支援 |
| 複雜度 | 簡單 | 較複雜 |

**預設選擇：SSE** -- 以較低的複雜度滿足 90% 的串流需求。

### 檔案上傳

```
Browser → POST /api/storage/upload (multipart/form-data) → Nginx → Core → Object Store
```

## 2. Frontend ↔ LiveKit: WebRTC

針對即時語音與視訊，使用 **LiveKit**（獨立的 Realtime 服務）。

```
                   ┌─────────────┐
                   │   Browser   │
                   │ (React SDK) │
                   └──────┬──────┘
                     WebRTC│wss://
                   ┌──────┴──────┐
                   │  LiveKit    │
                   │  Server     │
                   └──────┬──────┘
                     gRPC │
                   ┌──────┴──────┐
                   │  LiveKit    │
                   │  Agent      │
                   └──────┬──────┘
                          │
                  ┌───────┼───────┐
                  ▼       ▼       ▼
               [STT]   [LLM]   [TTS]
```

**流程**:
1. 前端向 Core 請求 **room token** (`POST /api/livekit/token`)
2. Core 透過 LiveKit Python SDK 產生 JWT 並回傳 token
3. 前端使用 token 連接至 LiveKit Server
4. LiveKit Agent 加入房間，透過 AI 流程處理音訊/視訊

## 3. 事件驅動通訊 (Core 內部)

單體架構內的模組間通訊使用 **Event Bus**。

詳見 [Event-Driven Architecture](./event-driven.md) 完整規範。

### 摘要

```
狀態變更 (非同步，不需回應)  → Event Bus
資料查詢 (同步，需要回應)    → Service import (進程內)
外部服務呼叫                → 透過 httpx 使用 HTTP
```

### 事件流程範例

```
Finance module → publish("finance.transaction.created", {...})
    ↓
Event Bus (進程內非同步)
    ↓
Quest module → 訂閱者檢查交易是否觸發成就
Admin module → 訂閱者記錄稽核軌跡
Plugin hooks → 觸發任何已註冊的插件 hook
```

### 規則

1. **事件用於寫入**: 當模組變更狀態時，發布一個事件。
2. **Service import 用於讀取**: 當模組需要來自另一個模組的資料時，直接呼叫其服務層 (service layer)。
3. **冪等處理器**: 事件訂閱者必須能優雅地處理重複事件。
4. **無循環依賴**: 如果 Module A 訂閱 Module B 的事件，且 Module B 也訂閱 Module A 的事件，請重新審視邊界劃分。

## 4. Core → Hot-Path 服務: HTTP + Events

Core Monolith 與 Realtime 及 Media 服務的通訊方式如下：

| 方向 | 模式 | 範例 |
|-----------|---------|---------|
| Core → Realtime | HTTP API | 產生 LiveKit room token |
| Core → Media | HTTP API | 請求 STT 逐字稿 |
| Realtime → Core | Redis Events | 房間成員加入 |
| Media → Core | Redis Events | 逐字稿轉換完成 |

```python
# Core 呼叫 Media 服務
import httpx

async def request_transcription(audio_url: str, user_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post("http://localhost:8831/transcribe", json={
            "audio_url": audio_url,
            "user_id": user_id,
        })
        return resp.json()
```

## 5. 資料庫存取

所有模組透過共用的連線池連接至 PostgreSQL，但各模組僅能存取其專屬的 schema：

```python
# 各模組使用具備 schema 範疇的查詢
await cur.execute("SELECT * FROM finance.transactions WHERE user_id = %s", [user_id])
```

驅動程式：支援非同步的 psycopg 3。

## 6. 身分驗證流程

```
Browser → POST /api/auth/login (憑證) → Nginx → Core (auth 模組)
Auth 模組 → 驗證憑證 → 建立 session → 設定簽署 cookie → Redis

Browser → GET /api/finance/transactions (簽署 cookie) → Nginx → Core
Auth 中間件 → 驗證 cookie → 從 Redis 載入使用者 → 檢查權限
Finance 模組 → 處理請求 (由中間件注入使用者資訊)
```

**規則**:
- Auth 中間件在所有受保護的路由前執行（同進程，無需轉發標頭）
- Session 狀態存於 Redis 以便快速查詢與跨實例共享
- 嚴禁將內部服務埠口暴露於網際網路

## 7. Hook/Plugin 整合

事件流經 Hook Engine，允許插件攔截並擴充行為：

```
模組發布事件
    → Event Bus 傳遞至模組訂閱者
    → Hook Engine 檢查已註冊的插件 hook
    → 執行插件 hook (具備權限隔離)
```

詳見 [Plugin System](./plugin-system.md) 的 hook 規範。

## 8. 可觀測性整合

所有通訊模式均整合了 OpenTelemetry：

- HTTP 請求：透過 FastAPI 中間件自動建立 span
- 事件：每一次事件發布/訂閱都會建立一個 trace span
- 外部呼叫：針對外發請求使用 httpx 儀表化 (instrumentation)
- 資料庫：針對查詢追蹤使用 psycopg 儀表化

詳見 [Observability](./observability.md) 了解細節。
