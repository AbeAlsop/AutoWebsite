"""Fail-closed Linux mount/process isolation for the untrusted coding agent."""

import os
import shutil
import sys
from pathlib import Path

from .config import Settings

SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
SANDBOX_ENV = {"PATH": SAFE_PATH, "LANG": "C.UTF-8"}


class AgentSandboxError(RuntimeError):
    pass


def sandbox_command(settings: Settings, workspace: Path, arguments: list[str]) -> list[str]:
    if sys.platform != "linux":
        raise AgentSandboxError("Agent execution requires Linux with bubblewrap; no unsandboxed fallback is allowed.")
    bwrap = shutil.which(settings.agent_sandbox_command, path=SAFE_PATH)
    agent = shutil.which(settings.agent_command, path=SAFE_PATH)
    if not bwrap or not agent:
        raise AgentSandboxError("Install bubblewrap and Codex in the system executable path before enabling jobs.")
    agent_path = Path(agent).resolve(strict=True)
    if not any(agent_path.is_relative_to(root) for root in (Path("/usr"), Path("/bin"))):
        raise AgentSandboxError("The agent executable must be installed under /usr or /bin, outside service credentials.")
    if not settings.agent_auth_file:
        raise AgentSandboxError("Set AUTOWEBSITE_AGENT_AUTH_FILE to a dedicated Codex auth.json file.")
    auth = Path(settings.agent_auth_file).resolve(strict=True)
    if not auth.is_file() or auth.stat().st_mode & 0o077:
        raise AgentSandboxError("The dedicated agent authentication file must be a regular file with mode 0600.")

    command = [
        bwrap, "--unshare-all", "--share-net", "--die-with-parent", "--new-session",
        "--cap-drop", "ALL", "--clearenv",
    ]
    # Never mount /, /srv, the service home, its environment file, Git credentials,
    # the database, other workspaces, or host /proc. Only system runtime files.
    for name in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
        path = Path(name)
        if path.is_symlink():
            command.extend(["--symlink", os.readlink(path), name])
        elif path.exists():
            command.extend(["--ro-bind", name, name])
    for name in ("/etc/ssl/certs", "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf"):
        if Path(name).exists():
            command.extend(["--ro-bind", name, name])
    command.extend([
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--tmpfs", "/home/agent", "--dir", "/home/agent/.codex",
        "--ro-bind", str(auth), "/home/agent/.codex/auth.json",
        "--ro-bind", str((settings.prompts_dir / "agent-result-schema.json").resolve(strict=True)), "/run/agent-result-schema.json",
        "--bind", str(workspace.resolve(strict=True)), "/workspace",
        "--chdir", "/workspace",
        "--setenv", "HOME", "/home/agent",
        "--setenv", "CODEX_HOME", "/home/agent/.codex",
        "--setenv", "PATH", SAFE_PATH,
        "--setenv", "LANG", "C.UTF-8",
        "--remount-ro", "/",
        "--", str(agent_path), *arguments,
    ])
    return command
