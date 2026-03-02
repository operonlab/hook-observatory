"""Memvault module — LLM memory persistence, semantic search, KAS profiles, Knowledge Graph."""

from .kg_routes import router as kg_router
from .routes import router

router.include_router(kg_router)
