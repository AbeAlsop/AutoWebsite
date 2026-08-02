from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings

app = FastAPI(title=settings.app_name)

templates = Jinja2Templates(directory=str(settings.templates_dir))

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def home() -> FileResponse:
    return FileResponse(settings.public_index)


@app.get("/admin", response_class=HTMLResponse)
async def admin_login(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "login.html",
        {"app_name": settings.app_name},
    )


@app.post("/login")
async def login(
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> RedirectResponse:
    # Phase 3 replaces this placeholder with bcrypt-backed authentication.
    _ = (username, password)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/logout")
async def logout() -> RedirectResponse:
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"app_name": settings.app_name},
    )


@app.post("/prompt")
async def submit_prompt(prompt: Annotated[str, Form()]) -> JSONResponse:
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
async def upload_file(file: Annotated[UploadFile, File()]) -> JSONResponse:
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
    return templates.TemplateResponse(
        request,
        "history.html",
        {"commits": []},
    )


@app.post("/rollback")
async def rollback(commit: Annotated[str, Form()]) -> JSONResponse:
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
