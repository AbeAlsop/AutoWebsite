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


def test_job_persists_selected_approved_uploads(tmp_path: Path):
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
    store.create_upload("image-upload", website.id, "image.png", tmp_path / "uploads" / "image-upload" / "content")
    store.complete_upload(
        "image-upload",
        website.id,
        checksum="checksum",
        mime_type="image/png",
        size=10,
        width=1,
        height=1,
    )

    job = store.create_job(website.id, "Use the image", "test-model", ("image-upload",))

    assert job.upload_ids == ("image-upload",)
    assert store.get_approved_uploads(website.id, job.upload_ids)[0].original_filename == "image.png"


def test_reprompt_supersedes_draft_and_uses_its_workspace(tmp_path: Path):
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
    initial = store.create_job(website.id, "Add a hero", "test-model")
    assert store.claim_next_job(website.id) is not None
    draft_workspace = tmp_path / "workspaces" / initial.id
    store.complete_job(initial.id, status="awaiting_review", workspace_directory=draft_workspace)

    followup = store.create_reprompt_job(
        initial.id, website.id, "Make the hero image smaller", "test-model", ()
    )

    assert store.get_job(initial.id, website.id).status == "superseded"
    assert followup.status == "queued"
    assert followup.workspace_directory == draft_workspace
    assert store.claim_next_job(website.id).id == followup.id


def test_rejecting_a_draft_unblocks_the_next_staging_job(tmp_path: Path):
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
    draft = store.create_job(website.id, "Unapproved change", "test-model")
    assert store.claim_next_job(website.id) is not None
    store.complete_job(draft.id, status="awaiting_review", workspace_directory=tmp_path / "draft")
    next_job = store.create_job(website.id, "New staging change", "test-model")

    assert store.claim_next_job(website.id) is None
    assert store.reject_job(draft.id, website.id)
    assert store.get_job(draft.id, website.id).status == "rejected"
    assert store.claim_next_job(website.id).id == next_job.id
