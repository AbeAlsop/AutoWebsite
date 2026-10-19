from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin.app import serve_preview_file
from admin.content_security import GENERATED_CONTENT_CSP, SandboxedStaticFiles


def test_preview_documents_have_opaque_origin_and_cannot_submit_forms(tmp_path):
    (tmp_path / "index.html").write_text('<script>fetch("/dashboard")</script>')
    (tmp_path / "image.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    for path in ("", "index.html", "image.svg"):
        response = serve_preview_file(tmp_path, path)
        policy = response.headers["content-security-policy"]
        assert "sandbox allow-scripts;" in policy
        assert "allow-same-origin" not in policy
        assert "connect-src 'none'" in policy
        assert "form-action 'none'" in policy
        assert response.headers["cache-control"] == "no-store"


def test_public_documents_and_304_responses_are_also_isolated(tmp_path):
    (tmp_path / "index.html").write_text("<script>document.cookie</script>")
    app = FastAPI()
    app.mount("/", SandboxedStaticFiles(directory=tmp_path, html=True))
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-security-policy"] == GENERATED_CONTENT_CSP
        cached = client.get("/", headers={"If-None-Match": response.headers["etag"]})
        assert cached.status_code == 304
        assert cached.headers["content-security-policy"] == GENERATED_CONTENT_CSP


def test_nginx_public_policy_matches_application():
    config = (Path(__file__).resolve().parents[1] / "deploy/nginx-autowebsite.conf").read_text()
    assert f'add_header Content-Security-Policy "{GENERATED_CONTENT_CSP}" always;' in config
