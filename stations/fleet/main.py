"""Fleet Station — multi-machine task dispatch service."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .dispatcher import Dispatcher
from .node_registry import NodeRegistry
from .task_store import TaskStore

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.yaml"


class DispatchRequest(BaseModel):
    command: str
    mode: str = "code"
    node: str | None = None
    timeout: int = 600


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = yaml.safe_load(CONFIG_PATH.read_text())
    registry = NodeRegistry(config.get("nodes", {}))
    store = TaskStore()
    dispatcher = Dispatcher(registry, store, config)

    app.state.config = config
    app.state.registry = registry
    app.state.store = store
    app.state.dispatcher = dispatcher

    # Background health check loop
    health_task = asyncio.create_task(registry.health_check_loop(config.get("health_interval", 30)))

    # Initial health check + warm pool
    for node in registry.all_nodes():
        try:
            await registry.check_node(node.name)
            if node.healthy:
                await dispatcher.ensure_warm_pool(node)
        except Exception as e:
            logger.warning("Startup check failed for %s: %s", node.name, e)

    logger.info("Fleet Station started on port %s", config.get("port", 10106))
    yield

    health_task.cancel()
    logger.info("Fleet Station shutting down")


app = FastAPI(title="Fleet Station", version="0.1.0", lifespan=lifespan)


# ── Routes ──


@app.get("/health")
async def health():
    registry: NodeRegistry = app.state.registry
    nodes = {n.name: n.healthy for n in registry.all_nodes()}
    all_healthy = all(nodes.values()) if nodes else False
    return {"status": "ok" if all_healthy else "degraded", "nodes": nodes}


@app.get("/nodes")
async def list_nodes():
    registry: NodeRegistry = app.state.registry
    return registry.to_dict()


@app.get("/nodes/{name}/health")
async def check_node_health(name: str):
    registry: NodeRegistry = app.state.registry
    node = registry.get(name)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node not found: {name}")
    healthy = await registry.check_node(name)
    return {"name": name, "healthy": healthy, "last_error": node.last_error}


@app.post("/tasks/dispatch")
async def dispatch_task(req: DispatchRequest):
    dispatcher: Dispatcher = app.state.dispatcher
    try:
        task = await dispatcher.dispatch(
            command=req.command,
            mode=req.mode,
            node_name=req.node,
            timeout=req.timeout,
        )
        return task.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/tasks")
async def list_tasks(
    status: str | None = Query(None),
    node: str | None = Query(None),
    limit: int = Query(50, le=200),
):
    store: TaskStore = app.state.store
    tasks = store.list_tasks(status=status, node=node, limit=limit)
    return [t.to_dict() for t in tasks]


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    store: TaskStore = app.state.store
    task = store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@app.get("/tasks/{task_id}/output")
async def get_task_output(task_id: str, lines: int = Query(200, le=1000)):
    dispatcher: Dispatcher = app.state.dispatcher
    task = app.state.store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    output = await dispatcher.get_output(task_id, lines=lines)
    return {"task_id": task_id, "status": task.status.value, "output": output}


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    dispatcher: Dispatcher = app.state.dispatcher
    task = await dispatcher.cancel(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or not cancellable")
    return task.to_dict()


if __name__ == "__main__":
    import uvicorn

    _config = yaml.safe_load(CONFIG_PATH.read_text())
    uvicorn.run(
        "stations.fleet.main:app",
        host=_config.get("host", "127.0.0.1"),
        port=_config.get("port", 10106),
        reload=False,
    )
