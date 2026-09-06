from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import create_session_token, read_session_token, verify_password
from .config import settings
from .csrf import create_csrf_token, validate_csrf_token
from .repository import Admin, RepositoryStore, Website
from .site import SingleSitePublisher

app = FastAPI(title=settings.app_name)
repository_store = RepositoryStore(settings.database_path)

templates = Jinja2Templates(directory=str(settings.templates_dir))

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


@app.on_event("startup")
async def initialize_repository_store() -> None:
    repository_store.initialize(
        bootstrap_username=settings.admin_username,
        bootstrap_password_hash=settings.admin_password_hash,
        bootstrap_website_name=settings.default_website_name,
        bootstrap_github_repo=settings.default_github_repo,
        bootstrap_working_directory=settings.default_website_directory,
        bootstrap_github_token_ref=settings.default_github_token_ref,
    )
    website = repository_store.get_active_website()
    if website is None:
        raise RuntimeError("No active website is configured.")
    SingleSitePublisher(
        repositories_root=settings.repositories_root,
        published_root=settings.published_root,
        source_directory=website.working_directory,
        starter_site_directory=settings.starter_site_dir,
    ).initialize()


def get_session_admin(request: Request) -> Admin | None:
    token = request.cookies.get(settings.session_cookie_name)
    session = read_session_token(token, settings.session_secret)
    if session is None:
        return None
    admin = repository_store.get_admin(session.username)
    if admin is None or (session.website_id is not None and session.website_id != admin.website_id):
        return None
    return admin


def require_admin(request: Request) -> Admin:
    admin = get_session_admin(request)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return admin


def get_authorized_website(admin: Admin) -> Website:
    website = repository_store.get_website_for_admin(admin.username, admin.website_id)
    if website is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Website access denied")
    return website


def require_csrf(request: Request, csrf_token: str | None) -> None:
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    if not validate_csrf_token(csrf_token, cookie_token, settings.session_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def add_csrf_cookie(response: Response, csrf_token: str) -> None:
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=settings.csrf_max_age_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )


def get_or_create_csrf_token(request: Request) -> str:
    csrf_token = request.cookies.get(settings.csrf_cookie_name)
    if validate_csrf_token(csrf_token, csrf_token, settings.session_secret):
        return csrf_token
    return create_csrf_token(settings.session_secret, settings.csrf_max_age_seconds)


def render_template_with_csrf(
    request: Request,
    template_name: str,
    context: dict[str, object],
    status_code: int = status.HTTP_200_OK,
) -> Response:
    csrf_token = get_or_create_csrf_token(request)
    response = templates.TemplateResponse(
        request,
        template_name,
        {**context, "csrf_token": csrf_token},
        status_code=status_code,
    )
    add_csrf_cookie(response, csrf_token)
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_login(request: Request) -> Response:
    if get_session_admin(request) is not None:
        return RedirectResponse(url="/dashboard", status_code=303)

    return render_template_with_csrf(
        request,
        "login.html",
        {"app_name": settings.app_name, "error": None},
    )


@app.post("/login")
async def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
) -> Response:
    require_csrf(request, csrf_token)
    admin = repository_store.get_admin(username)
    if admin is None or not verify_password(password, admin.password_hash):
        return render_template_with_csrf(
            request,
            "login.html",
            {"app_name": settings.app_name, "error": "Invalid username or password."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_session_token(
        username=username,
        secret=settings.session_secret,
        max_age_seconds=settings.session_max_age_seconds,
        website_id=admin.website_id,
    )
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )
    return response


@app.post("/logout")
async def logout(request: Request, csrf_token: Annotated[str | None, Form()] = None) -> RedirectResponse:
    require_admin(request)
    require_csrf(request, csrf_token)
    response = RedirectResponse(url="/admin", status_code=303)
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    admin = require_admin(request)
    website = get_authorized_website(admin)
    return render_template_with_csrf(
        request,
        "dashboard.html",
        {"app_name": settings.app_name, "username": admin.username, "website": website},
    )


@app.post("/prompt")
async def submit_prompt(
    request: Request,
    prompt: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
) -> JSONResponse:
    admin = require_admin(request)
    require_csrf(request, csrf_token)
    website = get_authorized_website(admin)
    # Phase 9 connects this endpoint to the coding agent.
    return JSONResponse(
        {
            "status": "accepted",
            "prompt": prompt,
            "website_id": website.id,
            "website_name": website.name,
            "message": "Prompt received. Agent execution is not enabled yet.",
        },
        status_code=202,
    )


@app.post("/upload")
async def upload_file(
    request: Request,
    file: Annotated[UploadFile, File()],
    csrf_token: Annotated[str | None, Form()] = None,
) -> JSONResponse:
    admin = require_admin(request)
    require_csrf(request, csrf_token)
    website = get_authorized_website(admin)
    # Phase 7 persists uploads and records metadata.
    contents = await file.read()
    return JSONResponse(
        {
            "status": "accepted",
            "filename": file.filename,
            "content_type": file.content_type,
            "size": len(contents),
            "website_id": website.id,
            "message": "Upload received. Persistent storage is not enabled yet.",
        },
        status_code=202,
    )


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request) -> HTMLResponse:
    admin = require_admin(request)
    website = get_authorized_website(admin)
    return render_template_with_csrf(
        request,
        "history.html",
        {"commits": [], "website": website},
    )


@app.post("/rollback")
async def rollback(
    request: Request,
    commit: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
) -> JSONResponse:
    admin = require_admin(request)
    require_csrf(request, csrf_token)
    website = get_authorized_website(admin)
    # Phase 14 implements rollback behavior.
    return JSONResponse(
        {
            "status": "queued",
            "commit": commit,
            "website_id": website.id,
            "message": "Rollback endpoint is available; rollback execution is not enabled yet.",
        },
        status_code=202,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# This route is deliberately registered last: the public static site is a fallback
# after all administration and health routes, and is served only from `published/current`.
app.mount("/", StaticFiles(directory=str(settings.public_site_dir), html=True, check_dir=False), name="public")
