"""Capture SDK client — progressive data enrichment pipeline."""

from typing import Any

from ._base import BaseClient


class CaptureClient(BaseClient):
    def __init__(self, **kwargs: Any):
        super().__init__(module="captures", **kwargs)

    def create(
        self,
        module: str,
        entity_type: str,
        payload: dict,
        raw_input: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "module": module,
            "entity_type": entity_type,
            "payload": payload,
        }
        if raw_input is not None:
            body["raw_input"] = raw_input
        return self._post("", body=body)

    def get(self, capture_id: str) -> dict:
        return self._get(f"/{capture_id}")

    def list(
        self,
        module: str | None = None,
        entity_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        return self._get(
            "",
            params={
                "module": module,
                "entity_type": entity_type,
                "status": status,
                "limit": limit,
                "offset": offset,
            },
        )

    def update(self, capture_id: str, payload: dict, raw_input: str | None = None) -> dict:
        body: dict[str, Any] = {"payload": payload}
        if raw_input is not None:
            body["raw_input"] = raw_input
        return self._patch(f"/{capture_id}", body=body)

    def promote(self, capture_id: str) -> dict:
        return self._post(f"/{capture_id}/promote")

    def delete(self, capture_id: str) -> None:
        self._delete(f"/{capture_id}")

    def stats(self) -> dict:
        return self._get("/stats")
