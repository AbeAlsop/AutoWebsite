from admin.auth import create_session_token, hash_password, read_session_token, verify_password


def test_password_hash_round_trip():
    password_hash = hash_password("correct horse battery staple")

    assert password_hash != "correct horse battery staple"
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)


def test_session_token_round_trip():
    token = create_session_token("admin", "test-secret", 60)
    session = read_session_token(token, "test-secret")

    assert session is not None
    assert session.username == "admin"


def test_session_token_rejects_tampering():
    token = create_session_token("admin", "test-secret", 60)
    payload, signature = token.split(".", 1)
    tampered = f"{payload}x.{signature}"

    assert read_session_token(tampered, "test-secret") is None
    assert read_session_token(token, "different-secret") is None


def test_session_token_rejects_expired_token():
    token = create_session_token("admin", "test-secret", -1)

    assert read_session_token(token, "test-secret") is None
