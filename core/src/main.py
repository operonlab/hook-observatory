"""Core service — Modular Monolith."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
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
app.add_middleware(StarletteSessionMiddleware, secret_key=settings.secret_key)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
from src.modules.paper.routes import router as paper_router  # noqa: E402

app.include_router(assistant_router, prefix="/api/assistant", tags=["assistant"])
app.include_router(capture_router, prefix="/api/captures", tags=["capture"])
register_capture_sse_events()
app.include_router(dailyos_router, prefix="/api/dailyos", tags=["dailyos"])
app.include_router(paper_router, prefix="/api/paper", tags=["paper"])
