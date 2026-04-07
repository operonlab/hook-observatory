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
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Layer 3: LLM Chat 浮層 (SSE streaming)              │ │
│  ├─────────────────────────────────────────────────────┤ │
│  │ Layer 2: Dashboard Widgets  │  Layer 1: 模組 SPA   │ │
│  └─────────────────────────────────────────────────────┘ │
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
        │   │auth  │taskflow │     │     └──────┬───────┘
        │   ├──────┼──────┤     │            │
        │   │finance│ideagraph │     │     ┌──────┴───────┐
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

完整規範詳見 [Event-Driven Architecture](./event-driven.md)。

**摘要**：
- 狀態變更（非同步） → Event Bus
- 資料查詢（同步） → Service import（進程內）
- 外部服務呼叫 → HTTP（httpx）

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
        resp = await client.post("http://localhost:10201/transcribe", json={  # stt station
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

完整認證架構詳見 [Auth Architecture](./auth.md)。

**摘要**：Browser → 簽署 cookie → Nginx → Core → Auth 中間件驗證 → 注入使用者資訊 → 模組處理請求。Session 狀態存於 Redis。

## 7. Hook/Plugin 整合

事件流經 Hook Engine，允許插件攔截並擴充行為。詳見 [Plugin System](./plugin-system.md)。

## 8. 可觀測性整合

所有通訊模式均整合 OpenTelemetry。詳見 [Observability](./observability.md)。
