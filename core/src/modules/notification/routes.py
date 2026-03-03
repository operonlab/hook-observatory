"""Notification routes — push subscription management + VAPID key endpoint."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.auth.deps import get_current_user
from src.shared.database import get_db
from src.shared.errors import BadRequestError, NotFoundError

from .schemas import PreferencesUpdate, SubscriptionCreate, SubscriptionResponse
from .services import notification_service

router = APIRouter()


@router.get("/vapid-key")
async def get_vapid_key():
    """Return the VAPID public key for client-side push subscription."""
    pub_key = getattr(settings, "vapid_public_key", "")
    if not pub_key:
        raise BadRequestError(
            "VAPID public key not configured",
            code="notification.vapid_not_configured",
        )
    return {"public_key": pub_key}


@router.post("/subscriptions", response_model=SubscriptionResponse)
async def create_subscription(
    data: SubscriptionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Register a push subscription for the current user."""
    user_id = user.get("id", user.get("user_id", ""))
    sub = await notification_service.subscribe(db, user_id, data)
    await db.commit()
    return notification_service.to_response(sub)


@router.delete("/subscriptions")
async def delete_subscription(
    endpoint: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Unsubscribe by endpoint URL."""
    success = await notification_service.unsubscribe(db, endpoint)
    if not success:
        raise NotFoundError("Subscription not found", code="notification.not_found")
    await db.commit()
    return {"unsubscribed": True}


@router.get("/subscriptions", response_model=list[SubscriptionResponse])
async def list_subscriptions(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List all active push subscriptions for the current user."""
    user_id = user.get("id", user.get("user_id", ""))
    return await notification_service.list_user_subscriptions(db, user_id)


@router.patch("/subscriptions/{sub_id}/preferences", response_model=SubscriptionResponse)
async def update_preferences(
    sub_id: str,
    data: PreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Update notification preferences for a subscription."""
    prefs = data.model_dump(exclude_unset=True)
    sub = await notification_service.update_preferences(db, sub_id, prefs)
    if not sub:
        raise NotFoundError("Subscription not found", code="notification.not_found")
    await db.commit()
    return notification_service.to_response(sub)
