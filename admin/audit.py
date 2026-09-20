from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Literal


LogCategory = Literal["agent", "web", "security"]
_SENSITIVE_FIELD_FRAGMENTS = ("password", "secret", "token", "cookie", "content", "filename", "path")


class AuditLogger:
    """Writes a small, durable, redacted audit trail for the single-site service."""

    def __init__(self, public_site_dir: Path | None = None) -> None:
        self.public_site_dir = public_site_dir
        # `uvicorn.access` expects five HTTP-request arguments. Use the process
        # logger instead so application audit records share the service journal
        # without being interpreted as access-log entries.
        self.logger = logging.getLogger("uvicorn.error")

    def initialize(self) -> None:
        """Use the web-server process log (systemd journal in production)."""

    def event(self, category: LogCategory, event: str, **fields: object) -> None:
        if not event or not event.replace("_", "").isalnum():
            raise ValueError("Audit event names may contain only letters, numbers, and underscores.")
        payload = {
            "timestamp": int(time.time()),
            "event": event,
            "active_release_id": self._active_release_id(),
            **self._safe_fields(fields),
        }
        self.logger.info(json.dumps({"category": category, **payload}, sort_keys=True, separators=(",", ":")))

    def _active_release_id(self) -> str | None:
        if self.public_site_dir is None:
            return None
        try:
            resolved = self.public_site_dir.resolve(strict=True)
        except OSError:
            return None
        return resolved.name

    @staticmethod
    def _safe_fields(fields: dict[str, object]) -> dict[str, object]:
        safe: dict[str, object] = {}
        for key, value in fields.items():
            if any(fragment in key.lower() for fragment in _SENSITIVE_FIELD_FRAGMENTS):
                raise ValueError(f"Sensitive audit field {key!r} is not allowed.")
            if key == "prompt":
                if not isinstance(value, str):
                    raise ValueError("Prompt audit values must be text.")
                safe[key] = " ".join(value.split())[:500]
            elif isinstance(value, (str, int, float, bool)) or value is None:
                safe[key] = value
            elif isinstance(value, (list, tuple)) and all(isinstance(item, (str, int, float, bool)) for item in value):
                safe[key] = list(value)
            else:
                raise ValueError(f"Unsupported audit value for {key!r}.")
        return safe
