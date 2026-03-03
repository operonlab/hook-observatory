"""Admin schemas — audit log query and response types."""

from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: str
    user_id: str | None = None
    module: str
    entity_type: str
    entity_id: str
    space_id: str | None = None
    action: str
    changes: dict | None = None
    snapshot: dict | None = None
    created_at: datetime


class AuditLogQuery(BaseModel):
    module: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    user_id: str | None = None
    space_id: str | None = None
    action: str | None = None
