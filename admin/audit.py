from __future__ import annotations

import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal


LogCategory = Literal["agent", "web", "security"]
_SENSITIVE_FIELD_FRAGMENTS = ("password", "prompt", "secret", "token", "cookie", "content", "filename", "path")


class AuditLogger:
    """Writes a small, durable, redacted audit trail for the single-site service."""

    def __init__(self, logs_root: Path, public_site_dir: Path | None = None) -> None:
        self.logs_root = logs_root
        self.public_site_dir = public_site_dir
        self._loggers: dict[LogCategory, logging.Logger] = {}

    def initialize(self) -> None:
        self.logs_root.mkdir(parents=True, exist_ok=True, mode=0o750)
        try:
            os.chmod(self.logs_root, 0o750)
        except OSError:
            pass
        for category in ("agent", "web", "security"):
            self._logger(category)  # Create the files at startup with known permissions.

    def event(self, category: LogCategory, event: str, **fields: object) -> None:
        if not event or not event.replace("_", "").isalnum():
            raise ValueError("Audit event names may contain only letters, numbers, and underscores.")
        payload = {
            "timestamp": int(time.time()),
            "event": event,
            "active_release_id": self._active_release_id(),
            **self._safe_fields(fields),
        }
        self._logger(category).info(json.dumps(payload, sort_keys=True, separators=(",", ":")))

    def _logger(self, category: LogCategory) -> logging.Logger:
        existing = self._loggers.get(category)
        if existing is not None:
            return existing
        logger = logging.getLogger(f"autowebsite.audit.{id(self)}.{category}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        destination = self.logs_root / f"{category}.log"
        handler = RotatingFileHandler(destination, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        try:
            os.chmod(destination, 0o640)
        except OSError:
            pass
        self._loggers[category] = logger
        return logger

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
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe[key] = value
            elif isinstance(value, (list, tuple)) and all(isinstance(item, (str, int, float, bool)) for item in value):
                safe[key] = list(value)
            else:
                raise ValueError(f"Unsupported audit value for {key!r}.")
        return safe
