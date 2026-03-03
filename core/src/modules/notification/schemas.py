"""Notification schemas — Pydantic request/response models."""

from datetime import datetime

from pydantic import BaseModel


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionCreate(BaseModel):
    endpoint: str
    keys: SubscriptionKeys
    user_agent: str | None = None
    app_scope: str = "/v2/"


class SubscriptionResponse(BaseModel):
    id: str
    user_id: str
    endpoint: str
    app_scope: str
    active: bool
    preferences: dict
    created_at: datetime
    updated_at: datetime


class PreferencesUpdate(BaseModel):
    sentinel: bool | None = None
    system: bool | None = None
    finance: bool | None = None
    taskflow: bool | None = None
    intelflow: bool | None = None
    agent: bool | None = None


class PushPayload(BaseModel):
    """Payload for triggering a push notification."""

    category: str  # sentinel, system, finance, taskflow, intelflow, agent
    title: str
    body: str = ""
    url: str = "/v2/"
    icon: str | None = None
    tag: str | None = None  # same tag → replace previous notification
    severity: str = "info"  # info, warning, critical
    user_id: str | None = None  # None = broadcast to all
