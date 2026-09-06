from admin.csrf import create_csrf_token, validate_csrf_token


def test_csrf_token_round_trip():
    token = create_csrf_token("test-secret", 60)

    assert validate_csrf_token(token, token, "test-secret")


def test_csrf_token_requires_form_and_cookie_match():
    token = create_csrf_token("test-secret", 60)
    other_token = create_csrf_token("test-secret", 60)

    assert not validate_csrf_token(token, other_token, "test-secret")
    assert not validate_csrf_token(token, None, "test-secret")
    assert not validate_csrf_token(None, token, "test-secret")


def test_csrf_token_rejects_tampering():
    token = create_csrf_token("test-secret", 60)
    nonce, expires_at, signature = token.rsplit(".", 2)
    tampered = f"{nonce}x.{expires_at}.{signature}"

    assert not validate_csrf_token(tampered, tampered, "test-secret")
    assert not validate_csrf_token(token, token, "different-secret")


def test_csrf_token_rejects_expired_token():
    token = create_csrf_token("test-secret", -1)

    assert not validate_csrf_token(token, token, "test-secret")
