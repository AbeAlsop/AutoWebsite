import asyncio
import importlib
import secrets
from dataclasses import replace
from unittest.mock import Mock

import pytest

from admin.config import settings


@pytest.mark.parametrize("secret", [
    "", " ", "change-this-session-secret", "replace-with-a-long-random-secret",
    "a" * 64, "short-but-varied", "example-" + "1234567890" * 4,
])
def test_rejects_missing_weak_and_example_secrets(secret):
    with pytest.raises(ValueError, match="AUTOWEBSITE_SESSION_SECRET"):
        replace(settings, session_secret=secret).validate_security()


def test_accepts_generated_secret():
    replace(settings, session_secret=secrets.token_urlsafe(32)).validate_security()


def test_startup_rejects_bad_secret_before_touching_database(monkeypatch):
    module = importlib.import_module("admin.app")
    store = Mock()
    monkeypatch.setattr(module, "settings", replace(settings, session_secret=""))
    monkeypatch.setattr(module, "repository_store", store)
    with pytest.raises(ValueError, match="AUTOWEBSITE_SESSION_SECRET"):
        asyncio.run(module.initialize_repository_store())
    store.initialize.assert_not_called()
