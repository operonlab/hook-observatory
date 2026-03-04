"""Notification API client -- Core module at /api/notification.

Wraps VAPID key, push subscriptions, and subscription preferences endpoints.

Usage:
    from workshop.clients.notification import NotificationClient

    client = NotificationClient()
    key = client.get_vapid_key()
    subs = client.list_subscriptions()
"""

from typing import Any

from ._base import BaseClient


class NotificationClient(BaseClient):
    """HTTP client for the Notification Core API module.

    Args:
        base_url: Core API URL. Defaults to CORE_API_URL env or localhost:8801.
        space_id: Space ID. Defaults to WORKSHOP_SPACE_ID env or "default".
        timeout: Default request timeout in seconds.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(module="notification", **kwargs)

    # ======================== VAPID Key ========================

    def get_vapid_key(self) -> dict:
        """Get VAPID public key. GET /vapid-key"""
        return self._get("/vapid-key")

    # ======================== Subscriptions ========================

    def list_subscriptions(self) -> list[dict]:
        """List current user's push subscriptions. GET /subscriptions"""
        return self._get("/subscriptions")

    def create_subscription(self, data: dict) -> dict:
        """Create a push subscription. POST /subscriptions

        Args:
            data: Dict with endpoint, p256dh, auth, keys.
        """
        return self._post("/subscriptions", data)

    def delete_subscription(self, endpoint: str) -> None:
        """Delete subscription by endpoint. DELETE /subscriptions

        Args:
            endpoint: The push subscription endpoint URL.
        """
        params = self._params({"endpoint": endpoint})
        self._request("DELETE", "/subscriptions", params=params)

    # ======================== Preferences ========================

    def update_preferences(self, sub_id: str, preferences: dict) -> dict:
        """Update subscription preferences. PATCH /subscriptions/{sub_id}/preferences

        Args:
            sub_id: Subscription ID.
            preferences: Dict of preference key-value pairs.
        """
        return self._patch(f"/subscriptions/{sub_id}/preferences", preferences)
