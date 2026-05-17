"""Core service — Modular Monolith."""

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request

from sdk_client.logging_context import JsonFormatterWithContext
from src.middleware.request_id import RequestInfoLoggingMiddleware
from src.modules.admin.middleware import AdminAuditMiddleware

# 2026-05-08: 確保 module-level logger（譬如 memvault.kg_routes）的 INFO/WARNING
# 會輸出到 stderr → /opt/homebrew/var/log/workshop/core/YYYY-MM-DD.error.log
# 否則 logger.info('[decay] ...') 等診斷訊息會被吞掉，少爺日後找不到 root cause
# 2026-05-17: 升級為 JSON file handler + text stderr (replaces basicConfig)
LOG_DIR = Path("/opt/homebrew/var/log/workshop/core")
LOG_DIR.mkdir(parents=True, exist_ok=True)
_root = logging.getLogger()
_root.handlers.clear()
_file_handler = RotatingFileHandler(
    LOG_DIR / "general.log", maxBytes=10 * 1024 * 1024, backupCount=5
)
_file_handler.setFormatter(JsonFormatterWithContext(service="core"))
_root.addHandler(_file_handler)
# Keep stderr too for launchd capture (text format ok)
_stderr_handler = logging.StreamHandler()
_stderr_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s"))
_root.addHandler(_stderr_handler)
_root.setLevel(logging.INFO)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.middleware.sessions import SessionMiddleware as StarletteSessionMiddleware

from src.config import settings
from src.events.bus import event_bus
from src.events.middleware import logging_middleware
from src.hooks.bus import hook_bus
from src.middleware.session import SessionMiddleware
from src.shared.errors import WorkshopError


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate secret_key before anything else
    if not settings.debug:
        settings.validate_secret_key()

    # Import event subscribers so @event_bus.on decorators register handlers
    import src.modules.capture.events  # auto-enrich on create
    import src.modules.dailyos.events
    import src.modules.finance.events
    import src.modules.intelflow.events  # cache invalidation
    import src.modules.invest.events
    import src.modules.memvault.events  # flywheel: block→KG, capture→KG, intelligence→memvault
    import src.modules.nodeflow.events  # registers @event_bus.on handlers
    import src.modules.notification.events
    import src.modules.paper.events  # paper cache invalidation
    import src.modules.taskflow.events  # noqa: F401

    # Backend selection: switch to Redis Streams if configured
    if settings.event_backend == "redis":
        from src.events.backends.memory import InMemoryBackend
        from src.events.backends.redis_streams import RedisStreamsBackend

        fallback = InMemoryBackend()
        redis_backend = RedisStreamsBackend(
            redis_url=str(settings.redis_url),
            fallback=fallback,
        )
        event_bus.set_backend(redis_backend)

    # Startup: init event bus, load plugins, register nodeflow
    event_bus.use(logging_middleware)
    await event_bus.start()
    await hook_bus.load_plugins(settings.plugin_dir)

    # Register nodeflow action registry + wildcard event subscriber
    from src.modules.nodeflow.registry import register_module_actions
    from src.modules.nodeflow.services import on_any_event

    register_module_actions()
    event_bus.channel("*").subscribe_handler(on_any_event)

    # Register KG auto-evolution handler (P5)
    from src.modules.memvault.kg_auto_evolve import register_auto_evolve_handler

    register_auto_evolve_handler()

    # Initialize Qdrant search index and register indexing handlers
    from src.events.handlers.qdrant_indexer import startup as qdrant_startup

    await qdrant_startup()

    # Start Redis push listener for station-originated notifications
    import asyncio
    import logging

    from src.modules.notification.redis_listener import redis_push_listener

    _listener_logger = logging.getLogger("src.modules.notification.redis_listener")

    def _log_listener_failure(task: asyncio.Task) -> None:
        """Done callback: log unexpected listener exits so they don't die silently."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _listener_logger.error("redis_push_listener terminated unexpectedly", exc_info=exc)

    push_task = asyncio.create_task(redis_push_listener())
    push_task.add_done_callback(_log_listener_failure)

    yield

    # Shutdown
    push_task.cancel()
    try:
        await push_task
    except asyncio.CancelledError:
        pass
    await event_bus.stop()

    # Cleanup ML worker subprocesses
    from src.shared import ax_bridge, omlx_bridge, rerank_bridge

    await omlx_bridge.shutdown()
    await rerank_bridge.shutdown()
    await ax_bridge.shutdown()


app = FastAPI(title="Workshop", version="0.1.0", lifespan=lifespan)


@app.exception_handler(WorkshopError)
async def workshop_error_handler(request: Request, exc: WorkshopError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": "Conflict: duplicate or constraint violation", "code": "conflict"},
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    import logging

    logging.getLogger(__name__).error("Unhandled exception on %s", request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "code": "internal.error"},
    )


app.add_middleware(SessionMiddleware)

# Starlette SessionMiddleware for authlib OAuth state (CSRF protection).
# This provides request.session used by authlib's authorize_redirect/authorize_access_token.
app.add_middleware(
    StarletteSessionMiddleware,
    secret_key=settings.secret_key,
    https_only=True,
    same_site="lax",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request ID + Structured HTTP Logging Middleware ---
# Innermost middleware (defined first → LIFO means event_accumulator wraps it).
# Generates/validates request_id, sets ContextVar, logs request_start/end,
# and injects X-Request-ID response header.
app.add_middleware(RequestInfoLoggingMiddleware)

# Admin audit middleware — isolate /api/admin/* mutations into admin-audit.log
# (compliance / GDPR-friendly). Reads user_id from ContextVar set by middleware above.
app.add_middleware(AdminAuditMiddleware)

# --- Event Accumulator Middleware ---
# Activates per-request event accumulation so that events published by
# BaseCRUDService hooks are held until after db.commit() succeeds.
# After call_next returns (route handler committed the DB), we flush the
# accumulated events — eliminating the race window between flush and commit.
@app.middleware("http")
async def event_accumulator_middleware(request, call_next):
    from src.shared.services import begin_event_accumulation, flush_pending_events

    begin_event_accumulation()
    try:
        response = await call_next(request)
    except Exception:
        # On unhandled exceptions the transaction would be rolled back;
        # drop accumulated events to avoid publishing stale data.
        from src.shared.services import _pending_events

        _pending_events.set(None)
        raise
    await flush_pending_events()
    return response


# --- Security Headers Middleware ---
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' wss: https:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'",
    )
    return response


# Mount domain modules
from src.modules.admin.routes import router as admin_router  # noqa: E402
from src.modules.auth.routes import router as auth_router  # noqa: E402
from src.modules.finance.routes import router as finance_router  # noqa: E402
from src.modules.ideagraph.routes import router as ideagraph_router  # noqa: E402
from src.modules.taskflow.routes import router as taskflow_router  # noqa: E402
from src.routes.health import router as health_router  # noqa: E402

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(finance_router, prefix="/api/finance", tags=["finance"])
app.include_router(taskflow_router, prefix="/api/taskflow", tags=["taskflow"])
app.include_router(ideagraph_router, prefix="/api/ideagraph", tags=["ideagraph"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(health_router, tags=["health"])

from src.modules.briefing.routes import router as briefing_router  # noqa: E402
from src.modules.intelflow.routes import router as intelflow_router  # noqa: E402
from src.modules.invest.routes import router as invest_router  # noqa: E402
from src.modules.matchcore.routes import router as matchcore_router  # noqa: E402
from src.modules.memvault.routes import router as memvault_router  # noqa: E402
from src.modules.nodeflow.routes import router as nodeflow_router  # noqa: E402
from src.modules.notification.routes import router as notification_router  # noqa: E402
from src.modules.skillpath.routes import router as skillpath_router  # noqa: E402
from src.modules.workpool.routes import router as workpool_router  # noqa: E402

app.include_router(notification_router, prefix="/api/notification", tags=["notification"])
app.include_router(briefing_router, prefix="/api/briefing", tags=["briefing"])
app.include_router(intelflow_router, prefix="/api/intelflow", tags=["intelflow"])
app.include_router(invest_router, prefix="/api/invest", tags=["invest"])
app.include_router(memvault_router, prefix="/api/memvault", tags=["memvault"])
app.include_router(skillpath_router, prefix="/api/skillpath", tags=["skillpath"])
app.include_router(workpool_router, prefix="/api/workpool", tags=["workpool"])
app.include_router(matchcore_router, prefix="/api/matchcore", tags=["matchcore"])
app.include_router(nodeflow_router, prefix="/api/nodeflow", tags=["nodeflow"])

from src.modules.assistant.routes import router as assistant_router  # noqa: E402
from src.modules.capture.routes import register_capture_sse_events  # noqa: E402
from src.modules.capture.routes import router as capture_router  # noqa: E402
from src.modules.dailyos.routes import router as dailyos_router  # noqa: E402
from src.modules.docvault.routes import router as docvault_router  # noqa: E402
from src.modules.paper.routes import router as paper_router  # noqa: E402

app.include_router(assistant_router, prefix="/api/assistant", tags=["assistant"])
app.include_router(capture_router, prefix="/api/captures", tags=["capture"])
register_capture_sse_events()
app.include_router(dailyos_router, prefix="/api/dailyos", tags=["dailyos"])
app.include_router(paper_router, prefix="/api/paper", tags=["paper"])
app.include_router(docvault_router, prefix="/api/docvault", tags=["docvault"])

from src.modules._diagnostics import router as _diagnostics_router  # noqa: E402

app.include_router(_diagnostics_router, prefix="/api", tags=["diagnostics"])
