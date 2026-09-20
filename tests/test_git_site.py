import subprocess
from pathlib import Path

from admin.git_site import GitSite


def _git(directory: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=directory, check=True, capture_output=True, text=True).stdout


def test_clones_configured_remote_and_commits_reviewed_workspace(tmp_path: Path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init")
    _git(seed, "config", "user.name", "Test")
    _git(seed, "config", "user.email", "test@example.invalid")
    (seed / "index.html").write_text("before", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "Initial")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "HEAD")

    checkout = tmp_path / "checkout"
    site = GitSite(checkout, str(remote))
    site.initialize()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "index.html").write_text("after", encoding="utf-8")
    site.replace_with(workspace)
    commit = site.commit_and_push("AI: Change homepage")

    assert commit.sha
    assert site.history()[0].sha == commit.sha
    assert (checkout / "index.html").read_text(encoding="utf-8") == "after"
    clone = tmp_path / "verify"
    subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True)
    assert (clone / "index.html").read_text(encoding="utf-8") == "after"
