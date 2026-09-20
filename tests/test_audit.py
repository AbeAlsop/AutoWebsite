import json

from admin.audit import AuditLogger


def test_emits_redacted_json_events_to_the_web_server_log(tmp_path, caplog):
    release = tmp_path / "published" / "releases" / "release-1"
    release.mkdir(parents=True)
    current = tmp_path / "published" / "current"
    current.symlink_to(release.relative_to(current.parent), target_is_directory=True)
    audit = AuditLogger(current)
    audit.initialize()
    with caplog.at_level("INFO", logger="uvicorn.error"):
        audit.event("web", "job_queued", website_id=1, job_id="job-1", upload_count=2)

    payload = json.loads(caplog.messages[-1])
    assert payload["event"] == "job_queued"
    assert payload["website_id"] == 1
    assert payload["job_id"] == "job-1"
    assert payload["active_release_id"] == "release-1"


def test_truncates_a_prompt_to_one_line(tmp_path, caplog):
    audit = AuditLogger()
    with caplog.at_level("INFO", logger="uvicorn.error"):
        audit.event("web", "job_queued", prompt="  Update\n" + "x" * 600)
    payload = json.loads(caplog.messages[-1])
    assert "\n" not in payload["prompt"]
    assert len(payload["prompt"]) == 500
    assert "timestamp" in payload


def test_rejects_sensitive_audit_fields(tmp_path):
    audit = AuditLogger()
    try:
        audit.event("security", "login_failed", password="not-safe")
    except ValueError as error:
        assert "Sensitive" in str(error)
    else:
        raise AssertionError("Passwords must never enter the audit log")
