from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "AutoWebsite"
    admin_dir: Path = Path(__file__).resolve().parent
    project_root: Path = admin_dir.parent

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

