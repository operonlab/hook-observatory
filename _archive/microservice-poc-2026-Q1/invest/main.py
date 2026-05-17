"""Invest Service — standalone FastAPI microservice extracted from Core Monolith.

Usage:
    INVEST_DB_URL=postgresql+asyncpg://localhost/workshop uvicorn main:app --port 10012
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from invest.routes import router as invest_router

from config import settings
from svc_shared.database import dispose_db, init_db
from svc_shared.errors import WorkshopError


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.DB_URL, debug=settings.DEBUG)
    yield
    await dispose_db()


app = FastAPI(
    title="Invest Service",
    description="Standalone invest module — microservice POC",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(invest_router, prefix="/api/invest")


@app.exception_handler(WorkshopError)
async def workshop_error_handler(request: Request, exc: WorkshopError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code, "module": exc.module},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "invest", "port": settings.PORT}
