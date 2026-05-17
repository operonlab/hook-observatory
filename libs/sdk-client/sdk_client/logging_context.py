"""Cross-service request context + JSON logger for workshop."""
from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import datetime, timezone

from pythonjsonlogger import jsonlogger

# Context vars — populated by middleware, read by formatter
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")
space_id_var: ContextVar[str] = ContextVar("space_id", default="")


def get_request_id() -> str:
    return request_id_var.get()


def set_request_id(rid: str) -> None:
    request_id_var.set(rid)


class JsonFormatterWithContext(jsonlogger.JsonFormatter):
    """JSON formatter that auto-injects request_id/user_id/space_id from ContextVar.

    Output schema matches schemas/log-event.schema.json:
      ts, level, logger, msg, service (required)
      request_id, user_id, space_id, module, duration_ms, status_code, ... (optional)
    """

    def __init__(self, service: str, *args, **kwargs):
        # Rename default fields to match schema
        kwargs.setdefault(
            "rename_fields",
            {
                "asctime": "ts",
                "levelname": "level",
                "name": "logger",
                "message": "msg",
            },
        )
        super().__init__(*args, **kwargs)
        self.service = service

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["service"] = self.service

        rid = request_id_var.get()
        if rid:
            log_record["request_id"] = rid

        uid = user_id_var.get()
        if uid:
            log_record["user_id"] = uid

        sid = space_id_var.get()
        if sid:
            log_record["space_id"] = sid

        # Normalize timestamp to ISO 8601 with timezone if not already set
        if "ts" not in log_record:
            log_record["ts"] = (
                datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
            )
