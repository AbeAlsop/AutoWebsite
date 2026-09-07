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
    default_website_name: str = os.getenv("AUTOWEBSITE_DEFAULT_WEBSITE_NAME", "Primary website")
    default_github_repo: str = os.getenv("AUTOWEBSITE_DEFAULT_GITHUB_REPO", "local/website")
    default_github_token_ref: str | None = os.getenv("AUTOWEBSITE_DEFAULT_GITHUB_TOKEN_REF")
    session_secret: str = os.getenv("AUTOWEBSITE_SESSION_SECRET", "change-this-session-secret")
    session_cookie_name: str = "autowebsite_session"
    session_max_age_seconds: int = 8 * 60 * 60
    csrf_cookie_name: str = "autowebsite_csrf"
    csrf_max_age_seconds: int = 8 * 60 * 60
    secure_cookies: bool = os.getenv("AUTOWEBSITE_SECURE_COOKIES", "true").lower() != "false"
    agent_enabled: bool = os.getenv("AUTOWEBSITE_AGENT_ENABLED", "false").lower() == "true"
    agent_command: str = os.getenv("AUTOWEBSITE_AGENT_COMMAND", "codex")
    agent_model: str = os.getenv("AUTOWEBSITE_AGENT_MODEL", "gpt-5.6-terra")
    agent_timeout_seconds: int = int(os.getenv("AUTOWEBSITE_AGENT_TIMEOUT_SECONDS", "900"))
    max_agent_output_bytes: int = int(os.getenv("AUTOWEBSITE_MAX_AGENT_OUTPUT_BYTES", "1048576"))
    max_upload_bytes: int = int(os.getenv("AUTOWEBSITE_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    max_upload_count: int = int(os.getenv("AUTOWEBSITE_MAX_UPLOAD_COUNT", "100"))
    upload_malware_scan_enabled: bool = os.getenv("AUTOWEBSITE_UPLOAD_MALWARE_SCAN_ENABLED", "true").lower() == "true"
    upload_malware_scan_command: str = os.getenv("AUTOWEBSITE_UPLOAD_MALWARE_SCAN_COMMAND", "clamscan")

    @property
    def templates_dir(self) -> Path:
        return self.admin_dir / "templates"

    @property
    def static_dir(self) -> Path:
        return self.admin_dir / "static"

    @property
    def database_path(self) -> Path:
        configured_path = os.getenv("AUTOWEBSITE_DATABASE_PATH")
        return Path(configured_path) if configured_path else self.project_root / "data" / "autowebsite.db"

    @property
    def repositories_root(self) -> Path:
        """Configured server-side root for website repositories on any OS."""
        configured_path = os.getenv("AUTOWEBSITE_REPOSITORIES_ROOT")
        return Path(configured_path) if configured_path else self.project_root / "repos"

    @property
    def published_root(self) -> Path:
        configured_path = os.getenv("AUTOWEBSITE_PUBLISHED_ROOT")
        return Path(configured_path) if configured_path else self.project_root / "published"

    @property
    def public_site_dir(self) -> Path:
        return self.published_root / "current"

    @property
    def starter_site_dir(self) -> Path:
        return self.project_root / "website"

    @property
    def workspaces_root(self) -> Path:
        configured_path = os.getenv("AUTOWEBSITE_WORKSPACES_ROOT")
        return Path(configured_path) if configured_path else self.project_root / "workspaces"

    @property
    def staging_root(self) -> Path:
        configured_path = os.getenv("AUTOWEBSITE_STAGING_ROOT")
        return Path(configured_path) if configured_path else self.project_root / "staging"

    @property
    def uploads_root(self) -> Path:
        configured_path = os.getenv("AUTOWEBSITE_UPLOADS_ROOT")
        return Path(configured_path) if configured_path else self.project_root / "uploads"

    @property
    def logs_root(self) -> Path:
        configured_path = os.getenv("AUTOWEBSITE_LOGS_ROOT")
        return Path(configured_path) if configured_path else self.project_root / "logs"

    @property
    def prompts_dir(self) -> Path:
        return self.project_root / "prompts"

    @property
    def default_website_directory(self) -> Path:
        configured_path = os.getenv("AUTOWEBSITE_DEFAULT_WEBSITE_DIRECTORY")
        return Path(configured_path) if configured_path else self.repositories_root / "active-site"


settings = Settings()
