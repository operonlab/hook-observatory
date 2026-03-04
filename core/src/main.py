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
    import src.modules.finance.events
    import src.modules.invest.events
    import src.modules.nodeflow.events  # noqa: F401
    import src.modules.notification.events  # noqa: F401

    # Startup: init event bus, load plugins, register nodeflow
    event_bus.use(logging_middleware)
    await event_bus.start()
    await hook_bus.load_plugins(settings.plugin_dir)

    # Register nodeflow action registry + wildcard event subscriber
    from src.modules.nodeflow.registry import register_module_actions
    from src.modules.nodeflow.services import on_any_event

    register_module_actions()
    event_bus.subscribe("*", on_any_event)

    # Start Redis push listener for station-originated notifications
    import asyncio

    from src.modules.notification.redis_listener import redis_push_listener

    push_task = asyncio.create_task(redis_push_listener())

    yield

    # Shutdown
    push_task.cancel()
    try:
        await push_task
    except asyncio.CancelledError:
        pass
    await event_bus.stop()


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

from src.modules.intelflow.routes import router as intelflow_router  # noqa: E402
from src.modules.invest.routes import router as invest_router  # noqa: E402
from src.modules.matchcore.routes import router as matchcore_router  # noqa: E402
from src.modules.memvault.routes import router as memvault_router  # noqa: E402
from src.modules.nodeflow.routes import router as nodeflow_router  # noqa: E402
from src.modules.notification.routes import router as notification_router  # noqa: E402
from src.modules.skillpath.routes import router as skillpath_router  # noqa: E402
from src.modules.workpool.routes import router as workpool_router  # noqa: E402

app.include_router(notification_router, prefix="/api/notification", tags=["notification"])
app.include_router(intelflow_router, prefix="/api/intelflow", tags=["intelflow"])
app.include_router(invest_router, prefix="/api/invest", tags=["invest"])
app.include_router(memvault_router, prefix="/api/memvault", tags=["memvault"])
app.include_router(skillpath_router, prefix="/api/skillpath", tags=["skillpath"])
app.include_router(workpool_router, prefix="/api/workpool", tags=["workpool"])
app.include_router(matchcore_router, prefix="/api/matchcore", tags=["matchcore"])
app.include_router(nodeflow_router, prefix="/api/nodeflow", tags=["nodeflow"])
