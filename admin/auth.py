from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import bcrypt


@dataclass(frozen=True)
class Session:
    username: str
    website_id: int | None
    expires_at: int


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_session_token(
    username: str, secret: str, max_age_seconds: int, website_id: int | None = None
) -> str:
    expires_at = int(time.time()) + max_age_seconds
    payload = {"username": username, "website_id": website_id, "expires_at": expires_at}
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded_payload = _urlsafe_encode(payload_bytes)
    signature = _sign(encoded_payload, secret)
    return f"{encoded_payload}.{signature}"


def read_session_token(token: str | None, secret: str) -> Session | None:
    if not token or "." not in token:
        return None

    encoded_payload, signature = token.rsplit(".", 1)
    expected_signature = _sign(encoded_payload, secret)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload_bytes = _urlsafe_decode(encoded_payload)
        payload = json.loads(payload_bytes)
        username = payload["username"]
        website_id = payload.get("website_id")
        if website_id is not None:
            website_id = int(website_id)
        expires_at = int(payload["expires_at"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    if expires_at <= int(time.time()):
        return None

    return Session(username=username, website_id=website_id, expires_at=expires_at)


def _sign(encoded_payload: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _urlsafe_encode(digest)


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
