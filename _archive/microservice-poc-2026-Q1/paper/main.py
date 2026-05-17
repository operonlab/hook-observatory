"""Paper Service — standalone FastAPI microservice extracted from Core Monolith.

Usage:
    PAPER_DB_URL=postgresql+asyncpg://localhost/workshop uvicorn main:app --port 10010
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from paper.routes import router as paper_router

from config import settings
from svc_shared.database import dispose_db, init_db
from svc_shared.errors import WorkshopError


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.DB_URL, debug=settings.DEBUG)
    yield
    await dispose_db()


app = FastAPI(
    title="Paper Service",
    description="Standalone paper module — microservice POC",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(paper_router, prefix="/api/paper")


@app.exception_handler(WorkshopError)
async def workshop_error_handler(request: Request, exc: WorkshopError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code, "module": exc.module},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "paper", "port": settings.PORT}
