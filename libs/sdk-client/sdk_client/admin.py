"""Admin API client -- Core module at /api/admin.

Wraps health check and audit log endpoints.

Usage:
    from sdk_client.admin import AdminClient

    client = AdminClient()
    health = client.status()
    logs = client.list_audit_logs(module="finance")
"""

from typing import Any

from ._base import BaseClient


class AdminClient(BaseClient):
    """HTTP client for the Admin Core API module.

    Args:
        base_url: Core API URL. Defaults to CORE_API_URL env or localhost:10000.
        space_id: Space ID. Defaults to WORKSHOP_SPACE_ID env or "default".
        timeout: Default request timeout in seconds.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(module="admin", **kwargs)

    # ======================== Health ========================

    def status(self) -> dict:
        """Health check. GET /status"""
        return self._get("/status")

    # ======================== Audit Logs ========================

    def list_audit_logs(
        self,
        module: str | None = None,
        entity_type: str | None = None,
        user_id: str | None = None,
        space_id: str | None = None,
        action: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List audit logs (paginated). GET /audit

        Args:
            module: Filter by module name.
            entity_type: Filter by entity type.
            user_id: Filter by user ID.
            space_id: Filter by space ID.
            action: Filter by action type.
            page: Page number (default 1).
            page_size: Items per page (default 20).
        """
        return self._get(
            "/audit",
            {
                "module": module,
                "entity_type": entity_type,
                "user_id": user_id,
                "space_id": space_id,
                "action": action,
                "page": page,
                "page_size": page_size,
            },
        )

    def get_entity_history(self, module: str, entity_type: str, entity_id: str) -> list[dict]:
        """Get audit history for a specific entity. GET /audit/{module}/{entity_type}/{entity_id}

        Args:
            module: Module name.
            entity_type: Entity type.
            entity_id: Entity ID.
        """
        return self._get(f"/audit/{module}/{entity_type}/{entity_id}")
