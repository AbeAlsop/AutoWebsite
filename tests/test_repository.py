from pathlib import Path

from admin.repository import RepositoryStore


def test_bootstrap_maps_admin_to_its_website(tmp_path: Path):
    store = RepositoryStore(tmp_path / "autowebsite.db")
    working_directory = tmp_path / "example-site"

    store.initialize(
        bootstrap_username="alice",
        bootstrap_password_hash="bcrypt-hash",
        bootstrap_website_name="Example site",
        bootstrap_github_repo="acme/example-site",
        bootstrap_working_directory=working_directory,
        bootstrap_github_token_ref="secret://github/acme-example-site",
    )

    admin = store.get_admin("alice")
    assert admin is not None
    website = store.get_website_for_admin("alice", admin.website_id)

    assert website is not None
    assert website.name == "Example site"
    assert website.github_repo == "acme/example-site"
    assert website.working_directory == working_directory.resolve()
    assert website.github_token == "secret://github/acme-example-site"


def test_admin_cannot_select_a_different_website_id(tmp_path: Path):
    store = RepositoryStore(tmp_path / "autowebsite.db")
    store.initialize(
        bootstrap_username="alice",
        bootstrap_password_hash="bcrypt-hash",
        bootstrap_website_name="Example site",
        bootstrap_github_repo="acme/example-site",
        bootstrap_working_directory=tmp_path / "example-site",
        bootstrap_github_token_ref=None,
    )

    admin = store.get_admin("alice")
    assert admin is not None
    assert store.get_website_for_admin("alice", admin.website_id + 1) is None
