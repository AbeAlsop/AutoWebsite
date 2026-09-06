from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time


def create_csrf_token(secret: str, max_age_seconds: int) -> str:
    nonce = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + max_age_seconds
    payload = f"{nonce}.{expires_at}"
    signature = _sign(payload, secret)
    return f"{payload}.{signature}"


def validate_csrf_token(submitted_token: str | None, cookie_token: str | None, secret: str) -> bool:
    if not submitted_token or not cookie_token:
        return False
    if not hmac.compare_digest(submitted_token, cookie_token):
        return False

    parts = submitted_token.rsplit(".", 2)
    if len(parts) != 3:
        return False

    nonce, expires_at_text, signature = parts
    payload = f"{nonce}.{expires_at_text}"
    expected_signature = _sign(payload, secret)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    try:
        expires_at = int(expires_at_text)
    except ValueError:
        return False

    return expires_at > int(time.time())


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
