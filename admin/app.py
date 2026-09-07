from __future__ import annotations

from typing import Annotated
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import create_session_token, read_session_token, verify_password
from .config import settings
from .csrf import create_csrf_token, validate_csrf_token
from .agent import JobRunner
from .repository import Admin, Job, RepositoryStore, Website
from .site import SingleSitePublisher

app = FastAPI(title=settings.app_name)
repository_store = RepositoryStore(settings.database_path)
job_runner = JobRunner(repository_store, settings)

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
    await job_runner.start(website)


@app.on_event("shutdown")
async def stop_job_runner() -> None:
    await job_runner.stop()


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


def get_authorized_job(admin: Admin, job_id: str) -> Job:
    job = repository_store.get_job(job_id, admin.website_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def get_staging_directory() -> Path:
    if job_runner.staging_area is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Staging is initializing")
    return job_runner.staging_area.current_revision().directory


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
        {
            "app_name": settings.app_name,
            "username": admin.username,
            "website": website,
            "jobs": repository_store.list_jobs(website.id),
            "staging_revision": get_staging_directory().name,
        },
    )


@app.post("/prompt")
async def submit_prompt(
    request: Request,
    prompt: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    admin = require_admin(request)
    require_csrf(request, csrf_token)
    website = get_authorized_website(admin)
    job = repository_store.create_job(website.id, prompt, settings.agent_model)
    job_runner.wake()
    return RedirectResponse(url=f"/dashboard#job-{job.id}", status_code=303)


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


@app.get("/jobs/{job_id}")
async def job_status(request: Request, job_id: str) -> dict[str, object]:
    admin = require_admin(request)
    job = get_authorized_job(admin, job_id)
    return serialize_job(job)


@app.get("/jobs/{job_id}/preview")
async def preview_directory_redirect(request: Request, job_id: str) -> RedirectResponse:
    admin = require_admin(request)
    job = get_authorized_job(admin, job_id)
    if job.workspace_directory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview is not available")
    if job.status not in {"awaiting_review", "approved"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Preview is not available for this job")
    return RedirectResponse(url=f"/jobs/{job_id}/preview/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/jobs/{job_id}/preview/", response_class=HTMLResponse)
@app.get("/jobs/{job_id}/preview/{asset_path:path}")
async def job_preview(request: Request, job_id: str, asset_path: str = "") -> Response:
    admin = require_admin(request)
    job = get_authorized_job(admin, job_id)
    if job.workspace_directory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview is not available")
    if job.status not in {"awaiting_review", "approved"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Preview is not available for this job")
    return serve_preview_file(job.workspace_directory, asset_path)


@app.get("/staging/preview")
async def staging_preview_directory_redirect(request: Request) -> RedirectResponse:
    require_admin(request)
    return RedirectResponse(url="/staging/preview/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/staging/preview/", response_class=HTMLResponse)
@app.get("/staging/preview/{asset_path:path}")
async def staging_preview(request: Request, asset_path: str = "") -> Response:
    require_admin(request)
    return serve_preview_file(get_staging_directory(), asset_path)


def serve_preview_file(directory: Path, asset_path: str) -> Response:
    root = directory.resolve(strict=True)
    requested = (root / asset_path).resolve(strict=False)
    try:
        requested.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview asset not found") from error
    if requested.is_dir():
        requested = requested / "index.html"
    if any(part in {".env", ".env.local", ".git", ".ssh"} for part in requested.relative_to(root).parts):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview asset not found")
    if not requested.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview asset not found")
    return FileResponse(requested, headers={"Cache-Control": "no-store"})


@app.post("/jobs/{job_id}/approve")
async def approve_job(
    request: Request,
    job_id: str,
    csrf_token: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    admin = require_admin(request)
    require_csrf(request, csrf_token)
    job = get_authorized_job(admin, job_id)
    if job.status != "awaiting_review" or job.workspace_directory is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is not awaiting review")
    if job_runner.staging_area is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Staging is initializing")
    job_runner.staging_area.apply_workspace(job.workspace_directory)
    if not repository_store.approve_job(job_id, admin.website_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is not awaiting review")
    job_runner.wake()
    return RedirectResponse(url=f"/dashboard#job-{job_id}", status_code=303)


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(
    request: Request,
    job_id: str,
    csrf_token: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    admin = require_admin(request)
    require_csrf(request, csrf_token)
    if not repository_store.request_cancel(job_id, admin.website_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job cannot be cancelled")
    return RedirectResponse(url=f"/dashboard#job-{job_id}", status_code=303)


@app.post("/jobs/{job_id}/retry")
async def retry_job(
    request: Request,
    job_id: str,
    csrf_token: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    admin = require_admin(request)
    require_csrf(request, csrf_token)
    previous = get_authorized_job(admin, job_id)
    if previous.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed or cancelled jobs can be retried")
    job = repository_store.create_job(admin.website_id, previous.prompt, settings.agent_model)
    job_runner.wake()
    return RedirectResponse(url=f"/dashboard#job-{job.id}", status_code=303)


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


def serialize_job(job: Job) -> dict[str, object]:
    return {
        "id": job.id,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "changed_files": list(job.changed_files),
        "error": job.error,
        "model": job.model,
        "preview_url": None if job.workspace_directory is None else f"/jobs/{job.id}/preview",
    }


# This route is deliberately registered last: the public static site is a fallback
# after all administration and health routes, and is served only from `published/current`.
app.mount("/", StaticFiles(directory=str(settings.public_site_dir), html=True, check_dir=False), name="public")
