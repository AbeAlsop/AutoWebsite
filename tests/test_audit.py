import json

from admin.audit import AuditLogger


def test_writes_redacted_json_events_to_the_requested_category(tmp_path):
    release = tmp_path / "published" / "releases" / "release-1"
    release.mkdir(parents=True)
    current = tmp_path / "published" / "current"
    current.symlink_to(release.relative_to(current.parent), target_is_directory=True)
    audit = AuditLogger(tmp_path / "logs", current)
    audit.initialize()
    audit.event("web", "job_queued", website_id=1, job_id="job-1", upload_count=2)

    payload = json.loads((tmp_path / "logs" / "web.log").read_text(encoding="utf-8"))
    assert payload["event"] == "job_queued"
    assert payload["website_id"] == 1
    assert payload["job_id"] == "job-1"
    assert payload["active_release_id"] == "release-1"
    assert "timestamp" in payload


def test_rejects_sensitive_audit_fields(tmp_path):
    audit = AuditLogger(tmp_path / "logs")
    try:
        audit.event("security", "login_failed", password="not-safe")
    except ValueError as error:
        assert "Sensitive" in str(error)
    else:
        raise AssertionError("Passwords must never enter the audit log")
