from pathlib import Path

from admin.site import SingleSitePublisher, SiteLayoutError


def test_initializes_source_and_publishes_atomic_release(tmp_path: Path):
    starter = tmp_path / "starter"
    starter.mkdir(parents=True)
    (starter / "index.html").write_text("first release", encoding="utf-8")

    publisher = SingleSitePublisher(
        repositories_root=tmp_path / "repos",
        published_root=tmp_path / "published",
        source_directory=tmp_path / "repos" / "active-site",
        starter_site_directory=starter,
    )

    first_release = publisher.initialize()
    assert (publisher.source_directory / "index.html").read_text(encoding="utf-8") == "first release"
    assert (publisher.current_release_pointer / "index.html").read_text(encoding="utf-8") == "first release"

    (publisher.source_directory / "index.html").write_text("second release", encoding="utf-8")
    second_release = publisher.publish()

    assert first_release.release_id != second_release.release_id
    assert publisher.current_release_pointer.is_symlink()
    assert (publisher.current_release_pointer / "index.html").read_text(encoding="utf-8") == "second release"
    assert (first_release.directory / "index.html").read_text(encoding="utf-8") == "first release"


def test_rejects_source_outside_repository_root(tmp_path: Path):
    starter = tmp_path / "starter"
    starter.mkdir(parents=True)
    (starter / "index.html").write_text("starter", encoding="utf-8")
    publisher = SingleSitePublisher(
        repositories_root=tmp_path / "repos",
        published_root=tmp_path / "published",
        source_directory=tmp_path / "outside-site",
        starter_site_directory=starter,
    )

    try:
        publisher.initialize()
    except SiteLayoutError:
        pass
    else:
        raise AssertionError("Source directories outside the repository root must be rejected")


def test_publishes_a_staging_directory_without_mutating_source(tmp_path: Path):
    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "index.html").write_text("live", encoding="utf-8")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "index.html").write_text("staged", encoding="utf-8")
    publisher = SingleSitePublisher(
        repositories_root=tmp_path / "repos",
        published_root=tmp_path / "published",
        source_directory=tmp_path / "repos" / "active-site",
        starter_site_directory=starter,
    )
    publisher.initialize()

    release = publisher.publish_directory(staging)

    assert (publisher.current_release_pointer / "index.html").read_text(encoding="utf-8") == "staged"
    assert (publisher.source_directory / "index.html").read_text(encoding="utf-8") == "live"
    assert release.directory.is_dir()
