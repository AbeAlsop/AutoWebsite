# AutoWebsite
AI-powered self-editing website platform.

## Admin server

Run the FastAPI admin server from the repository root:

```bash
cd /Users/abe/Code/AutoWebsite
.venv/bin/uvicorn admin.app:app --reload
```

Phase 3 authentication expects credentials from environment variables:

```bash
export AUTOWEBSITE_ADMIN_USERNAME="admin"
export AUTOWEBSITE_ADMIN_PASSWORD_HASH="<bcrypt hash>"
export AUTOWEBSITE_SESSION_SECRET="<long random secret>"
```

Generate a bcrypt hash without storing the plaintext password:

```bash
.venv/bin/python -c "from admin.auth import hash_password; print(hash_password('your password'))"
```
