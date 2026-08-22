from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import create_session_token, read_session_token, verify_password
from .config import settings

app = FastAPI(title=settings.app_name)

templates = Jinja2Templates(directory=str(settings.templates_dir))

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


def get_session_username(request: Request) -> str | None:
    token = request.cookies.get(settings.session_cookie_name)
    session = read_session_token(token, settings.session_secret)
    if session is None:
        return None
    return session.username


def require_admin(request: Request) -> str:
    username = get_session_username(request)
    if username != settings.admin_username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return username


@app.get("/", response_class=HTMLResponse)
async def home() -> FileResponse:
    return FileResponse(settings.public_index)


@app.get("/admin", response_class=HTMLResponse)
async def admin_login(request: Request) -> Response:
    if get_session_username(request) == settings.admin_username:
        return RedirectResponse(url="/dashboard", status_code=303)

    return templates.TemplateResponse(
        request,
        "login.html",
        {"app_name": settings.app_name, "error": None},
    )


@app.post("/login")
async def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    if username != settings.admin_username or not verify_password(password, settings.admin_password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"app_name": settings.app_name, "error": "Invalid username or password."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_session_token(
        username=username,
        secret=settings.session_secret,
        max_age_seconds=settings.session_max_age_seconds,
    )
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@app.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/admin", status_code=303)
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    username = require_admin(request)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"app_name": settings.app_name, "username": username},
    )


@app.post("/prompt")
async def submit_prompt(request: Request, prompt: Annotated[str, Form()]) -> JSONResponse:
    require_admin(request)
    # Phase 9 connects this endpoint to the coding agent.
    return JSONResponse(
        {
            "status": "accepted",
            "prompt": prompt,
            "message": "Prompt received. Agent execution is not enabled yet.",
        },
        status_code=202,
    )


@app.post("/upload")
async def upload_file(request: Request, file: Annotated[UploadFile, File()]) -> JSONResponse:
    require_admin(request)
    # Phase 7 persists uploads and records metadata.
    contents = await file.read()
    return JSONResponse(
        {
            "status": "accepted",
            "filename": file.filename,
            "content_type": file.content_type,
            "size": len(contents),
            "message": "Upload received. Persistent storage is not enabled yet.",
        },
        status_code=202,
    )


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request) -> HTMLResponse:
    require_admin(request)
    return templates.TemplateResponse(
        request,
        "history.html",
        {"commits": []},
    )


@app.post("/rollback")
async def rollback(request: Request, commit: Annotated[str, Form()]) -> JSONResponse:
    require_admin(request)
    # Phase 14 implements rollback behavior.
    return JSONResponse(
        {
            "status": "queued",
            "commit": commit,
            "message": "Rollback endpoint is available; rollback execution is not enabled yet.",
        },
        status_code=202,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
