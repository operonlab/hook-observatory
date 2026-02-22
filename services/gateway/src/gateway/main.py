"""Gateway service — API routing, auth, health aggregation."""

from fastapi import FastAPI

app = FastAPI(title="Gateway", version="0.0.1")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "gateway", "version": "0.0.1"}
