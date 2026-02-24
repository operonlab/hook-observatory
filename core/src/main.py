"""Core service — Modular Monolith."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.middleware.session import SessionMiddleware
from src.events.bus import event_bus
from src.events.middleware import logging_middleware
from src.hooks.bus import hook_bus


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
from src.routes.health import router as health_router  # noqa: E402

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(health_router, tags=["health"])

# Future: finance, quest, muse routers
