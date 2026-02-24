"""Core service — Modular Monolith."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import settings
from src.middleware.session import SessionMiddleware
from src.events.bus import event_bus
from src.events.middleware import logging_middleware
from src.hooks.bus import hook_bus
from src.shared.errors import WorkshopError


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init event bus, load plugins
    event_bus.use(logging_middleware)
    await event_bus.start()
    await hook_bus.load_plugins(settings.plugin_dir)
    yield
    # Shutdown
    await event_bus.stop()


app = FastAPI(title="Workshop", version="0.1.0", lifespan=lifespan)


@app.exception_handler(WorkshopError)
async def workshop_error_handler(request: Request, exc: WorkshopError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
    )


app.add_middleware(SessionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount domain modules
from src.modules.auth.routes import router as auth_router  # noqa: E402
from src.modules.finance.routes import router as finance_router  # noqa: E402
from src.modules.taskflow.routes import router as taskflow_router  # noqa: E402
from src.modules.ideagraph.routes import router as ideagraph_router  # noqa: E402
from src.modules.admin.routes import router as admin_router  # noqa: E402
from src.routes.health import router as health_router  # noqa: E402

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(finance_router, prefix="/api/finance", tags=["finance"])
app.include_router(taskflow_router, prefix="/api/taskflow", tags=["taskflow"])
app.include_router(ideagraph_router, prefix="/api/ideagraph", tags=["ideagraph"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(health_router, tags=["health"])

from src.modules.intelflow.routes import router as intelflow_router  # noqa: E402
from src.modules.memvault.routes import router as memvault_router  # noqa: E402
from src.modules.skillpath.routes import router as skillpath_router  # noqa: E402
from src.modules.workpool.routes import router as workpool_router  # noqa: E402
from src.modules.matchcore.routes import router as matchcore_router  # noqa: E402

app.include_router(intelflow_router, prefix="/api/intelflow", tags=["intelflow"])
app.include_router(memvault_router, prefix="/api/memvault", tags=["memvault"])
app.include_router(skillpath_router, prefix="/api/skillpath", tags=["skillpath"])
app.include_router(workpool_router, prefix="/api/workpool", tags=["workpool"])
app.include_router(matchcore_router, prefix="/api/matchcore", tags=["matchcore"])
