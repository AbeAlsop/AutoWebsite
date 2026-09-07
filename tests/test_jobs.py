from pathlib import Path

from admin.repository import RepositoryStore


def test_jobs_are_persistent_and_serially_claimed(tmp_path: Path):
    store = RepositoryStore(tmp_path / "autowebsite.db")
    store.initialize(
        bootstrap_username="alice",
        bootstrap_password_hash="bcrypt-hash",
        bootstrap_website_name="Example site",
        bootstrap_github_repo="acme/example-site",
        bootstrap_working_directory=tmp_path / "repos" / "active-site",
        bootstrap_github_token_ref=None,
    )
    website = store.get_active_website()
    assert website is not None

    job = store.create_job(website.id, "Change the headline", "test-model")
    claimed = store.claim_next_job(website.id)

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == "running"
    assert store.claim_next_job(website.id) is None

    store.complete_job(
        job.id,
        status="awaiting_review",
        changed_files=["index.html"],
        diff="--- source/index.html\n+++ proposed/index.html\n",
        workspace_directory=tmp_path / "workspaces" / job.id,
    )
    finished = store.get_job(job.id, website.id)

    assert finished is not None
    assert finished.status == "awaiting_review"
    assert finished.changed_files == ("index.html",)
    assert store.approve_job(job.id, website.id)
    assert store.get_job(job.id, website.id).status == "approved"


def test_review_blocks_later_jobs_until_approval(tmp_path: Path):
    store = RepositoryStore(tmp_path / "autowebsite.db")
    store.initialize(
        bootstrap_username="alice",
        bootstrap_password_hash="bcrypt-hash",
        bootstrap_website_name="Example site",
        bootstrap_github_repo="acme/example-site",
        bootstrap_working_directory=tmp_path / "repos" / "active-site",
        bootstrap_github_token_ref=None,
    )
    website = store.get_active_website()
    assert website is not None

    first = store.create_job(website.id, "First change", "test-model")
    assert store.claim_next_job(website.id) is not None
    store.complete_job(first.id, status="awaiting_review")
    second = store.create_job(website.id, "Second change", "test-model")

    assert store.claim_next_job(website.id) is None
    assert store.approve_job(first.id, website.id)
    claimed_second = store.claim_next_job(website.id)
    assert claimed_second is not None
    assert claimed_second.id == second.id
