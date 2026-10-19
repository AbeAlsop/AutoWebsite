import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from admin.agent import CodexAgent
from admin.agent_sandbox import AgentSandboxError, SANDBOX_ENV, sandbox_command
from admin.config import settings


def configured(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text('{"OPENAI_API_KEY":"test-only"}')
    auth.chmod(0o600)
    return replace(settings, agent_enabled=True, agent_auth_file=str(auth), agent_command="/bin/sh")


def test_no_unsandboxed_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr("admin.agent_sandbox.sys.platform", "darwin")
    launch = Mock()
    monkeypatch.setattr("admin.agent.subprocess.Popen", launch)
    result = CodexAgent(configured(tmp_path)).run(tmp_path, "test", "test", [])
    assert "no unsandboxed fallback" in result.error
    launch.assert_not_called()


def test_command_excludes_service_home_environment_and_git_credentials(monkeypatch, tmp_path):
    config = configured(tmp_path)
    monkeypatch.setattr("admin.agent_sandbox.sys.platform", "linux")
    monkeypatch.setattr("admin.agent_sandbox.shutil.which", lambda executable, **kwargs: executable)
    command = sandbox_command(config, tmp_path, ["-c", "true"])
    assert "--clearenv" in command
    assert "--unshare-all" in command
    assert "--proc" in command
    assert "--cap-drop" in command
    assert "--remount-ro" in command
    assert str(Path.home()) not in command
    assert str(settings.database_path) not in command
    assert "AUTOWEBSITE_SESSION_SECRET" not in SANDBOX_ENV
    for offset, arg in enumerate(command):
        if arg == "--bind":
            assert command[offset + 1:offset + 3] == [str(tmp_path.resolve()), "/workspace"]


def test_rejects_world_readable_authentication_file(monkeypatch, tmp_path):
    config = configured(tmp_path)
    Path(config.agent_auth_file).chmod(0o644)
    monkeypatch.setattr("admin.agent_sandbox.sys.platform", "linux")
    monkeypatch.setattr("admin.agent_sandbox.shutil.which", lambda executable, **kwargs: executable)
    with pytest.raises(AgentSandboxError, match="0600"):
        sandbox_command(config, tmp_path, [])


def test_process_receives_only_allowlisted_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOWEBSITE_SESSION_SECRET", "synthetic-marker")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/private/ssh-agent.sock")
    monkeypatch.setattr("admin.agent.sandbox_command", lambda *args: ["/sandbox"])
    process = Mock(returncode=0)
    monkeypatch.setattr("admin.agent.collect_output", lambda *args: ("done", None))
    launch = Mock(return_value=process)
    monkeypatch.setattr("admin.agent.subprocess.Popen", launch)
    assert CodexAgent(configured(tmp_path)).run(tmp_path, "test", "test", []).error is None
    assert launch.call_args.kwargs["env"] == SANDBOX_ENV
    assert launch.call_args.kwargs["close_fds"] is True


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("bwrap"), reason="Requires Linux and bubblewrap")
def test_real_sandbox_hides_host_files_and_secrets(tmp_path):
    config = configured(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "service-secret"
    secret.write_text("must-not-be-readable")
    script = (
        'test -z "$AUTOWEBSITE_SESSION_SECRET" && '
        f'test ! -e "{secret}" && '
        'test ! -e /srv && test ! -e /home/agent/.ssh && '
        'test -r /home/agent/.codex/auth.json && '
        '! echo overwrite > /home/agent/.codex/auth.json && '
        'echo isolated > /workspace/result.txt'
    )
    result = subprocess.run(sandbox_command(config, workspace, ["-c", script]),
                            env={**SANDBOX_ENV, "AUTOWEBSITE_SESSION_SECRET": "synthetic-marker"},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert (workspace / "result.txt").read_text().strip() == "isolated"
    assert "test-only" in Path(config.agent_auth_file).read_text()
