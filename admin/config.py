from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "AutoWebsite"
    admin_dir: Path = Path(__file__).resolve().parent
    project_root: Path = admin_dir.parent
    admin_username: str = os.getenv("AUTOWEBSITE_ADMIN_USERNAME", "admin")
    admin_password_hash: str = os.getenv("AUTOWEBSITE_ADMIN_PASSWORD_HASH", "")
    session_secret: str = os.getenv("AUTOWEBSITE_SESSION_SECRET", "change-this-session-secret")
    session_cookie_name: str = "autowebsite_session"
    session_max_age_seconds: int = 8 * 60 * 60

    @property
    def templates_dir(self) -> Path:
        return self.admin_dir / "templates"

    @property
    def static_dir(self) -> Path:
        return self.admin_dir / "static"

    @property
    def public_index(self) -> Path:
        return self.project_root / "website" / "index.html"


settings = Settings()
