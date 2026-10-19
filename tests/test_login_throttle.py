import asyncio
import importlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from fastapi import HTTPException
from starlette.requests import Request
import pytest

from admin.config import settings
from admin.csrf import create_csrf_token
from admin.login_throttle import LoginRateLimiter
from admin.repository import Admin


def limiter(tmp_path, **kwargs):
    value = LoginRateLimiter(tmp_path / "test.db", **kwargs)
    value.initialize()
    return value


def test_account_budget_survives_new_ips_and_process_restart(tmp_path):
    first = limiter(tmp_path)
    for i in range(5):
        assert first.reserve("admin", f"ip-{i}") == 0
    assert limiter(tmp_path).reserve("admin", "new-ip") > 0


def test_ip_budget_applies_across_unknown_accounts(tmp_path):
    value = limiter(tmp_path, ip_limit=2)
    assert value.reserve(None, "ip") == 0
    assert value.reserve(None, "ip") == 0
    assert value.reserve(None, "ip") > 0


def test_global_budget_bounds_distributed_attempts(tmp_path):
    value = limiter(tmp_path, global_limit=2)
    assert value.reserve(None, "ip1") == 0
    assert value.reserve(None, "ip2") == 0
    assert value.reserve(None, "ip3") > 0


def test_budget_expires_and_attempt_reservation_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr("admin.login_throttle.time.time", lambda: 1000)
    value = limiter(tmp_path)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda i: value.reserve("admin", str(i)), range(10)))
    assert results.count(0) == 5
    monkeypatch.setattr("admin.login_throttle.time.time", lambda: 1301)
    assert value.reserve("admin", "ip") == 0


def test_route_throttles_before_bcrypt_and_checks_password_off_loop(tmp_path, monkeypatch):
    module = importlib.import_module("admin.app")
    config = replace(settings, session_secret="test-only-secret-" * 3)
    monkeypatch.setattr(module, "settings", config)
    monkeypatch.setattr(module, "login_limiter", limiter(tmp_path, account_limit=1))
    monkeypatch.setattr(module.repository_store, "get_admin", lambda _: Admin("admin", "hash", 1))
    token = create_csrf_token(config.session_secret, 60)
    request = Request({"type": "http", "client": ("127.0.0.1", 1234),
                       "headers": [(b"cookie", f"{config.csrf_cookie_name}={token}".encode())]})
    calls = []
    loop_thread = threading.get_ident()
    def verify(*_):
        calls.append(threading.get_ident())
        return True
    monkeypatch.setattr(module, "verify_password", verify)
    async def attempt():
        assert (await module.login(request, "admin", "password", token)).status_code == 303
        with pytest.raises(HTTPException) as raised:
            await module.login(request, "admin", "password", token)
        assert raised.value.status_code == 429
        assert int(raised.value.headers["Retry-After"]) > 0
    asyncio.run(attempt())
    assert len(calls) == 1
    assert calls[0] != loop_thread
