"""Bound memory before reading untrusted process output or workspace files."""

import hashlib
import os
import selectors
import stat
import subprocess
import time
from pathlib import Path

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TREE_BYTES = 100 * 1024 * 1024
MAX_TREE_ENTRIES = 2000
MAX_TEXT_DIFF_BYTES = 256 * 1024
IGNORED_NAMES = {".git", ".DS_Store", "__pycache__", ".autowebsite-upload-inputs"}
SENSITIVE_NAMES = {".env", ".env.local", ".git", ".ssh"}


def inventory(directory: Path, *, validate_workspace=False) -> dict[str, Path]:
    """Stat the entire bounded tree before reading any payloads; never follow links."""
    result = {}
    pending = [directory]
    entries = total = 0
    while pending:
        with os.scandir(pending.pop()) as children:
            for child in children:
                entries += 1
                if entries > MAX_TREE_ENTRIES:
                    raise RuntimeError("Workspace exceeds the entry-count limit.")
                path = Path(child.path)
                if validate_workspace and path.name in SENSITIVE_NAMES:
                    raise RuntimeError(f"Sensitive path is not allowed: {path.name}.")
                if path.name in IGNORED_NAMES and not validate_workspace:
                    continue
                mode = child.stat(follow_symlinks=False)
                if stat.S_ISLNK(mode.st_mode):
                    raise RuntimeError("Symlinks are not permitted in a workspace.")
                if stat.S_ISDIR(mode.st_mode):
                    pending.append(path)
                    continue
                if not stat.S_ISREG(mode.st_mode):
                    raise RuntimeError("Workspaces may contain regular files only.")
                if mode.st_size > MAX_FILE_BYTES:
                    raise RuntimeError(f"File exceeds {MAX_FILE_BYTES} bytes: {path.name}.")
                total += mode.st_size
                if total > MAX_TREE_BYTES:
                    raise RuntimeError("Workspace exceeds the total-byte limit.")
                result[path.relative_to(directory).as_posix()] = path
    return result


def read_chunks(path: Path):
    # O_NONBLOCK avoids blocking on a FIFO substituted after the inventory pass.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise RuntimeError("Workspace file is not regular or exceeds the size limit.")
        total = 0
        while chunk := source.read(min(65536, MAX_FILE_BYTES - total + 1)):
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise RuntimeError("Workspace file grew beyond the size limit.")
            yield chunk


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for chunk in read_chunks(path):
        digest.update(chunk)
    return digest.hexdigest()


def diff_text(path: Path) -> bytes | None:
    """Keep difflib's line tables bounded too, independently of the output cap."""
    data = bytearray()
    for chunk in read_chunks(path):
        if len(data) + len(chunk) > MAX_TEXT_DIFF_BYTES or b"\0" in chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def collect_output(process, limit: int, timeout: float, terminate) -> tuple[str, str | None]:
    """Drain a merged binary pipe incrementally, killing a noisy or stalled child."""
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(process.args, timeout)
                if not selector.select(min(remaining, 0.1)):
                    continue
                chunk = os.read(process.stdout.fileno(), min(65536, limit - len(output) + 1))
                if not chunk:
                    break
                available = limit - len(output)
                output.extend(chunk[:available])
                if len(chunk) > available:
                    terminate(process)
                    return output.decode("utf-8", errors="ignore"), "Agent output exceeded its byte limit."
        process.wait(timeout=max(0, deadline - time.monotonic()))
        return output.decode("utf-8", errors="ignore"), None
    except subprocess.TimeoutExpired:
        terminate(process)
        return output.decode("utf-8", errors="ignore"), "Agent execution timed out."
    finally:
        if process.poll() is None:
            terminate(process)
        process.stdout.close()
