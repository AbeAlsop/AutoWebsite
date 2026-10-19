import os
import subprocess
import sys
import time
from dataclasses import replace

import pytest

from admin.agent import CodexAgent, JobRunner
from admin.config import settings
from admin.repository import RepositoryStore
from admin.resource_limits import MAX_FILE_BYTES, collect_output, inventory, read_chunks


def run_child(script, *, limit=1024, timeout=3):
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    output, error = collect_output(process, limit, timeout, CodexAgent._terminate_process)
    assert process.poll() is not None
    assert process.stdout.closed
    return output, error


@pytest.mark.parametrize("fd", [1, 2])
def test_runaway_stdout_and_stderr_are_killed_at_limit(fd):
    output, error = run_child(f'import os\nwhile True: os.write({fd}, b"x" * 8192)')
    assert len(output.encode()) == 1024
    assert "byte limit" in error


def test_exact_output_limit_is_allowed():
    output, error = run_child('import os; os.write(1, b"x" * 1024)')
    assert len(output) == 1024
    assert error is None


def test_silent_child_times_out_without_blocking_on_pipe():
    started = time.monotonic()
    _, error = run_child('import time; time.sleep(30)', timeout=0.1)
    assert "timed out" in error
    assert time.monotonic() - started < 3


def test_agent_marks_output_overflow_as_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("admin.agent.sandbox_command", lambda *args: [
        sys.executable, "-c", 'import os; os.write(1, b"x" * 4096)',
    ])
    agent = CodexAgent(replace(settings, agent_enabled=True, max_agent_output_bytes=100))
    result = agent.run(tmp_path, "test", "test", [])
    assert "byte limit" in result.error
    assert len(result.output) == 100


def runner(tmp_path, output_limit=1024):
    return JobRunner(RepositoryStore(tmp_path / "unused.db"),
                     replace(settings, max_agent_output_bytes=output_limit))


def test_oversized_sparse_file_rejected_without_reading_payload(tmp_path, monkeypatch):
    path = tmp_path / "oversized.bin"
    with path.open("wb") as stream:
        stream.truncate(MAX_FILE_BYTES + 1)
    def no_read(*_):
        pytest.fail("oversized payload must not be read")
    monkeypatch.setattr("admin.agent.file_hash", no_read)
    with pytest.raises(RuntimeError, match="exceeds"):
        runner(tmp_path)._files_by_relative_path(tmp_path)


def test_aggregate_bytes_and_entry_limits_are_checked(tmp_path, monkeypatch):
    (tmp_path / "one").write_bytes(b"123456")
    (tmp_path / "two").write_bytes(b"123456")
    monkeypatch.setattr("admin.resource_limits.MAX_TREE_BYTES", 10)
    with pytest.raises(RuntimeError, match="total-byte"):
        inventory(tmp_path)
    monkeypatch.setattr("admin.resource_limits.MAX_TREE_BYTES", 100)
    monkeypatch.setattr("admin.resource_limits.MAX_TREE_ENTRIES", 1)
    with pytest.raises(RuntimeError, match="entry-count"):
        inventory(tmp_path)


def test_symlinks_and_special_files_are_rejected(tmp_path):
    (tmp_path / "link").symlink_to("missing")
    with pytest.raises(RuntimeError, match="Symlinks"):
        inventory(tmp_path)
    (tmp_path / "link").unlink()
    os.mkfifo(tmp_path / "fifo")
    with pytest.raises(RuntimeError, match="regular files"):
        inventory(tmp_path)
    with pytest.raises(RuntimeError, match="not regular"):
        list(read_chunks(tmp_path / "fifo"))


def test_read_rechecks_size_after_inventory(tmp_path):
    path = tmp_path / "grow"
    path.write_bytes(b"small")
    inventory(tmp_path)
    with path.open("wb") as stream:
        stream.truncate(MAX_FILE_BYTES + 1)
    with pytest.raises(RuntimeError, match="size limit"):
        list(read_chunks(path))


def test_diff_is_bounded_and_large_text_is_not_loaded_into_difflib(tmp_path):
    source, workspace = tmp_path / "source", tmp_path / "workspace"
    source.mkdir()
    workspace.mkdir()
    (workspace / "index.html").write_text("small change\n" * 100)
    changed, diff = runner(tmp_path, 100)._diff_directories(source, workspace)
    assert changed == ["index.html"]
    assert len(diff.encode()) <= 100
    assert diff.endswith("[diff truncated]")
    (workspace / "index.html").write_bytes(b"line\n" * 100000)
    _, diff = runner(tmp_path)._diff_directories(source, workspace)
    assert "diff omitted" in diff


def test_changed_file_limit_precedes_diff_text_reads(tmp_path, monkeypatch):
    source, workspace = tmp_path / "source", tmp_path / "workspace"
    source.mkdir()
    workspace.mkdir()
    for i in range(51):
        (workspace / str(i)).write_text("x")
    def no_diff(*_):
        pytest.fail("too many changes must not reach difflib")
    monkeypatch.setattr("admin.agent.diff_text", no_diff)
    with pytest.raises(RuntimeError, match="more than 50"):
        runner(tmp_path)._diff_directories(source, workspace)
