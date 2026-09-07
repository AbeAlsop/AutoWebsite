from __future__ import annotations

import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path


class SiteLayoutError(RuntimeError):
    """Raised when a source or release path falls outside the permitted layout."""


_ALLOWED_PUBLIC_SUFFIXES = {
    ".avif", ".css", ".gif", ".htm", ".html", ".ico", ".jpeg", ".jpg",
    ".js", ".json", ".map", ".mjs", ".png", ".svg", ".txt", ".webmanifest",
    ".webp", ".woff", ".woff2", ".xml",
}
_FORBIDDEN_PUBLIC_NAMES = {".env", ".git", ".ssh", "id_rsa"}
_IGNORED_RELEASE_NAMES = (".git", ".DS_Store", ".autowebsite-upload-inputs")
_MAX_PUBLIC_FILE_BYTES = 10 * 1024 * 1024


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
            shutil.copytree(starter, source, symlinks=False, ignore=shutil.ignore_patterns(*_IGNORED_RELEASE_NAMES))

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
        return self.publish_directory(source)

    def publish_directory(self, directory: Path) -> PublishedRelease:
        """Publish a validated server-side directory as a new immutable release."""
        source = directory.resolve(strict=True)
        if not source.is_dir():
            raise SiteLayoutError("Cannot publish because the release directory is missing.")
        self._validate_tree(source, source)

        self.releases_directory.mkdir(parents=True, exist_ok=True)
        release_id = uuid.uuid4().hex
        release_directory = self.releases_directory / release_id
        shutil.copytree(source, release_directory, symlinks=False, ignore=shutil.ignore_patterns(*_IGNORED_RELEASE_NAMES))
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
        index = directory / "index.html"
        if not index.is_file() or index.is_symlink():
            raise SiteLayoutError("A published site must contain a regular top-level index.html file.")
        for path in directory.rglob("*"):
            relative_parts = path.relative_to(directory).parts
            # A Git checkout is never copied into a release; allow its private
            # metadata while validating the publishable working tree.
            if any(part in {".git", ".autowebsite-upload-inputs"} for part in relative_parts):
                continue
            # macOS Finder metadata is not part of a web release and is already
            # excluded by copytree during publication.
            if path.name == ".DS_Store":
                continue
            if path.is_symlink():
                resolved = path.resolve(strict=True)
                cls._require_within(resolved, root, "symlink target")
                raise SiteLayoutError("Published sites cannot contain symlinks.")
            if path.is_dir():
                continue
            if not path.is_file():
                raise SiteLayoutError("Published sites may contain regular files only.")
            if path.name in _FORBIDDEN_PUBLIC_NAMES:
                raise SiteLayoutError(f"The file {path.name} is not allowed in a published site.")
            if path.suffix.lower() not in _ALLOWED_PUBLIC_SUFFIXES:
                raise SiteLayoutError(f"The non-static file {path.name} is not allowed in a published site.")
            file_mode = path.stat().st_mode
            if file_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                raise SiteLayoutError(f"Executable file {path.name} is not allowed in a published site.")
            if path.stat().st_size > _MAX_PUBLIC_FILE_BYTES:
                raise SiteLayoutError(f"The file {path.name} exceeds the public release size limit.")
