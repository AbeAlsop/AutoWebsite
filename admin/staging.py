from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path


class StagingError(RuntimeError):
    """Raised when the private staging area is invalid or cannot be advanced."""


@dataclass(frozen=True)
class StagingRevision:
    revision_id: str
    directory: Path


class StagingArea:
    """Maintains private, cumulative website proposals independently of production."""

    def __init__(self, source_directory: Path, staging_root: Path) -> None:
        self.source_directory = source_directory
        self.staging_root = staging_root

    @property
    def revisions_directory(self) -> Path:
        return self.staging_root / "revisions"

    @property
    def current_pointer(self) -> Path:
        return self.staging_root / "current"

    def initialize(self) -> StagingRevision:
        self.staging_root.mkdir(parents=True, exist_ok=True)
        if self.current_pointer.exists() or self.current_pointer.is_symlink():
            return self.current_revision()
        source = self.source_directory.resolve(strict=True)
        if not source.is_dir():
            raise StagingError("The website source directory must be a directory.")
        return self._create_revision(source)

    def current_revision(self) -> StagingRevision:
        if not (self.current_pointer.exists() or self.current_pointer.is_symlink()):
            raise StagingError("The staging area has not been initialized.")
        resolved = self.current_pointer.resolve(strict=True)
        self._require_within(resolved, self.revisions_directory)
        return StagingRevision(resolved.name, resolved)

    def apply_workspace(self, workspace: Path) -> StagingRevision:
        """Advance staging to an immutable copy of an approved job workspace."""
        source = workspace.resolve(strict=True)
        if not source.is_dir():
            raise StagingError("The approved workspace is missing.")
        self._validate_tree(source)
        return self._create_revision(source)

    def _create_revision(self, source: Path) -> StagingRevision:
        self.revisions_directory.mkdir(parents=True, exist_ok=True)
        revision_id = uuid.uuid4().hex
        destination = self.revisions_directory / revision_id
        self._validate_tree(source)
        shutil.copytree(
            source,
            destination,
            symlinks=False,
            ignore=shutil.ignore_patterns(".git", ".DS_Store", "__pycache__", ".autowebsite-upload-inputs"),
        )
        self._switch_current(destination)
        return StagingRevision(revision_id, destination)

    def _switch_current(self, revision_directory: Path) -> None:
        revision = self._require_within(revision_directory, self.revisions_directory)
        root = self.staging_root.resolve(strict=True)
        pointer = root / "current"
        if pointer.exists() and not pointer.is_symlink():
            raise StagingError("The staging current pointer must be a symlink or absent.")
        temporary_pointer = root / f".current-{uuid.uuid4().hex}"
        try:
            os.symlink(revision.relative_to(root), temporary_pointer, target_is_directory=True)
            os.replace(temporary_pointer, pointer)
        finally:
            if temporary_pointer.is_symlink():
                temporary_pointer.unlink()

    @staticmethod
    def _require_within(path: Path, root: Path) -> Path:
        resolved_path = path.resolve(strict=False)
        resolved_root = root.resolve(strict=False)
        try:
            resolved_path.relative_to(resolved_root)
        except ValueError as error:
            raise StagingError("A staging path escaped its configured root.") from error
        return resolved_path

    @staticmethod
    def _validate_tree(directory: Path) -> None:
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise StagingError(f"Symlinks are not allowed in staging: {path}")
