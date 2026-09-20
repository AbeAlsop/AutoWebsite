from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitSiteError(RuntimeError):
    """Raised when the configured single-site Git checkout cannot be used safely."""


@dataclass(frozen=True)
class GitCommit:
    sha: str
    subject: str


@dataclass(frozen=True)
class GitHistoryEntry:
    sha: str
    timestamp: int
    subject: str


class GitSite:
    """Owns the trusted Git checkout; browser input never selects its remote or path."""

    def __init__(self, directory: Path, configured_remote: str) -> None:
        self.directory = directory
        self.configured_remote = configured_remote

    def initialize(self) -> None:
        if (self.directory / ".git").is_dir():
            self._verify_remote()
            return
        if self.directory.exists() and any(self.directory.iterdir()):
            raise GitSiteError("The configured website directory is not an empty Git checkout location.")
        self.directory.parent.mkdir(parents=True, exist_ok=True)
        self._run("clone", self.remote_url, str(self.directory), cwd=self.directory.parent)

    def replace_with(self, workspace: Path) -> None:
        source = workspace.resolve(strict=True)
        if not source.is_dir():
            raise GitSiteError("The reviewed workspace is unavailable.")
        self._verify_remote()
        for child in self.directory.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in source.iterdir():
            if child.name in {".git", ".DS_Store", ".autowebsite-upload-inputs"}:
                continue
            destination = self.directory / child.name
            if child.is_dir():
                shutil.copytree(child, destination, symlinks=False)
            else:
                shutil.copy2(child, destination)

    def commit_and_push(self, message: str) -> GitCommit:
        self._run("add", "--all")
        changed = self._run("status", "--porcelain").stdout.strip()
        if changed:
            self._run("commit", "-m", message)
        self._run("push", "origin", "HEAD")
        sha = self._run("rev-parse", "HEAD").stdout.strip()
        subject = self._run("log", "-1", "--format=%s").stdout.strip()
        return GitCommit(sha=sha, subject=subject)

    def history(self, limit: int = 50) -> list[GitHistoryEntry]:
        output = self._run("log", f"--max-count={limit}", "--format=%H%x1f%ct%x1f%s").stdout
        entries: list[GitHistoryEntry] = []
        for line in output.splitlines():
            sha, timestamp, subject = line.split("\x1f", 2)
            entries.append(GitHistoryEntry(sha=sha, timestamp=int(timestamp), subject=subject))
        return entries

    def revert_and_push(self, commit: str) -> GitCommit:
        if not commit or any(character not in "0123456789abcdef" for character in commit.lower()) or len(commit) < 7:
            raise GitSiteError("The requested commit is invalid.")
        self._run("revert", "--no-edit", commit)
        self._run("push", "origin", "HEAD")
        sha = self._run("rev-parse", "HEAD").stdout.strip()
        subject = self._run("log", "-1", "--format=%s").stdout.strip()
        return GitCommit(sha=sha, subject=subject)

    @property
    def remote_url(self) -> str:
        remote = self.configured_remote.strip()
        if "://" in remote or remote.startswith("git@") or remote.startswith("/") or remote.startswith("."):
            return remote
        return f"https://github.com/{remote.removesuffix('.git')}.git"

    def _verify_remote(self) -> None:
        actual = self._run("remote", "get-url", "origin").stdout.strip()
        if actual != self.remote_url:
            raise GitSiteError("The checkout origin does not match the configured website Git location.")

    def _run(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", *args], cwd=cwd or self.directory, check=False, capture_output=True, text=True
            )
        except FileNotFoundError as error:
            raise GitSiteError("Git is not installed on the host.") from error
        if result.returncode != 0:
            raise GitSiteError(f"Git {' '.join(args[:2])} failed.")
        return result
