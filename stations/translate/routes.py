"""Translate Station API routes."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from config import config
from providers.base import TranslationError
from schemas import (
    BatchTranslateRequest,
    BatchTranslateResponse,
    TranslateRequest,
    TranslateResponse,
)
from workflow import workflow

import db as translate_db

router = APIRouter()


@router.get("/health")
async def health():
    """Health check with provider status."""
    providers = workflow._ensure_providers()
    status = {}
    for p in providers:
        status[p.name] = await p.is_available()
    return {"status": "ok", "service": "translate", "port": config.port, "providers": status}


@router.post("/translate", response_model=TranslateResponse)
async def translate(req: TranslateRequest):
    """Translate text using cascading providers."""
    try:
        return await workflow.translate(
            text=req.text,
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            preferred_provider=req.provider,
        )
    except TranslationError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/translate/batch", response_model=BatchTranslateResponse)
async def translate_batch(req: BatchTranslateRequest):
    """Batch translate multiple texts."""
    try:
        results = await workflow.translate_batch(
            texts=req.texts,
            source_lang=req.source_lang,
            target_lang=req.target_lang,
        )
        total_chars = sum(r.char_count for r in results)
        total_cost = sum(r.estimated_cost_usd for r in results)
        return BatchTranslateResponse(
            results=results,
            total_chars=total_chars,
            total_cost_usd=total_cost,
        )
    except TranslationError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/usage")
async def usage():
    """Today's usage stats and budget."""
    stats = await translate_db.get_usage_stats()
    daily_cost = await translate_db.get_daily_cost()
    return {
        "date": date.today().isoformat(),
        "providers": stats,
        "daily_budget_usd": config.daily_budget_usd,
        "budget_remaining_usd": max(0, config.daily_budget_usd - daily_cost),
    }
