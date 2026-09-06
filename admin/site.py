from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path


class SiteLayoutError(RuntimeError):
    """Raised when a source or release path falls outside the permitted layout."""


@dataclass(frozen=True)
class PublishedRelease:
    release_id: str
    directory: Path


class SingleSitePublisher:
    """Owns the trusted source and immutable public-release layout for one site."""

    def __init__(
        self,
        *,
        repositories_root: Path,
        published_root: Path,
        source_directory: Path,
        starter_site_directory: Path,
    ) -> None:
        self.repositories_root = repositories_root
        self.published_root = published_root
        self.source_directory = source_directory
        self.starter_site_directory = starter_site_directory

    @property
    def releases_directory(self) -> Path:
        return self.published_root / "releases"

    @property
    def current_release_pointer(self) -> Path:
        return self.published_root / "current"

    def initialize(self) -> PublishedRelease:
        self.repositories_root.mkdir(parents=True, exist_ok=True)
        self.published_root.mkdir(parents=True, exist_ok=True)
        source = self._require_within(self.source_directory, self.repositories_root, "source directory")

        if not source.exists():
            starter = self.starter_site_directory.resolve(strict=True)
            self._validate_tree(starter, starter)
            shutil.copytree(starter, source, symlinks=False)

        if not source.is_dir():
            raise SiteLayoutError("The active-site source path must be a directory.")
        self._validate_tree(source, source)

        current = self.current_release_pointer
        if current.exists() or current.is_symlink():
            resolved = current.resolve(strict=True)
            self._require_within(resolved, self.releases_directory, "current release")
            return PublishedRelease(resolved.name, resolved)
        return self.publish()

    def publish(self) -> PublishedRelease:
        source = self._require_within(self.source_directory, self.repositories_root, "source directory")
        if not source.is_dir():
            raise SiteLayoutError("Cannot publish because the active-site source is missing.")
        self._validate_tree(source, source)

        self.releases_directory.mkdir(parents=True, exist_ok=True)
        release_id = uuid.uuid4().hex
        release_directory = self.releases_directory / release_id
        shutil.copytree(source, release_directory, symlinks=False, ignore=shutil.ignore_patterns(".git", ".DS_Store"))
        self._switch_current_release(release_directory)
        return PublishedRelease(release_id, release_directory)

    def _switch_current_release(self, release_directory: Path) -> None:
        release = self._require_within(release_directory, self.releases_directory, "release directory")
        published_root = self.published_root.resolve(strict=True)
        pointer = published_root / "current"
        if pointer.exists() and not pointer.is_symlink():
            raise SiteLayoutError("The current release pointer must be a symlink or absent.")

        temporary_pointer = published_root / f".current-{uuid.uuid4().hex}"
        relative_target = release.relative_to(published_root)
        try:
            os.symlink(relative_target, temporary_pointer, target_is_directory=True)
            os.replace(temporary_pointer, pointer)
        finally:
            if temporary_pointer.is_symlink():
                temporary_pointer.unlink()

    @staticmethod
    def _require_within(path: Path, root: Path, label: str) -> Path:
        resolved_root = root.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        try:
            resolved_path.relative_to(resolved_root)
        except ValueError as error:
            raise SiteLayoutError(f"The {label} must be inside its configured root.") from error
        return resolved_path

    @classmethod
    def _validate_tree(cls, directory: Path, root: Path) -> None:
        for path in directory.rglob("*"):
            if path.is_symlink():
                resolved = path.resolve(strict=True)
                cls._require_within(resolved, root, "symlink target")
