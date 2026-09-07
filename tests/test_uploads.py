import asyncio
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import UploadFile

from admin.config import settings
from admin.repository import RepositoryStore
from admin.uploads import UploadManager, UploadRejected


def _store(tmp_path: Path) -> tuple[RepositoryStore, int]:
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
    return store, website.id


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content))


def test_image_upload_is_quarantined_then_persisted_with_manifests(tmp_path: Path):
    store, website_id = _store(tmp_path)
    configured = replace(settings, project_root=tmp_path, max_upload_bytes=1024)
    manager = UploadManager(store, configured)
    manager._scan_for_malware = lambda path: None  # type: ignore[method-assign]
    image = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (320).to_bytes(4, "big") + (200).to_bytes(4, "big")

    stored = asyncio.run(manager.store_upload(website_id, _upload("../../portfolio.png", image)))

    assert stored.upload.status == "approved"
    assert stored.upload.scan_status == "clean"
    assert stored.upload.original_filename == "portfolio.png"
    assert stored.upload.mime_type == "image/png"
    assert (stored.upload.width, stored.upload.height) == (320, 200)
    upload_directory = configured.uploads_root / "active-site" / stored.upload.id
    assert (upload_directory / "content").read_bytes() == image
    assert not (upload_directory / "quarantine.bin").exists()
    manifest = json.loads((upload_directory / "manifest.json").read_text())
    assert manifest["checksum"] == stored.upload.checksum
    gallery = json.loads((configured.uploads_root / "active-site" / "gallery.json").read_text())
    assert gallery["images"][0]["upload_id"] == stored.upload.id


def test_invalid_upload_is_rejected_and_payload_is_removed(tmp_path: Path):
    store, website_id = _store(tmp_path)
    configured = replace(settings, project_root=tmp_path)
    manager = UploadManager(store, configured)
    manager._scan_for_malware = lambda path: None  # type: ignore[method-assign]

    with pytest.raises(UploadRejected, match="not allowed"):
        asyncio.run(manager.store_upload(website_id, _upload("notes.txt", b"not an allowed file")))

    rejected = store.list_uploads(website_id)
    assert len(rejected) == 1
    assert rejected[0].status == "rejected"
    assert list((configured.uploads_root / "active-site" / rejected[0].id).glob("quarantine.bin")) == []


def test_allowed_image_records_when_malware_scanning_is_disabled(tmp_path: Path):
    store, website_id = _store(tmp_path)
    configured = replace(settings, project_root=tmp_path, upload_malware_scan_enabled=False)
    manager = UploadManager(store, configured)
    image = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1).to_bytes(4, "big") * 2

    stored = asyncio.run(manager.store_upload(website_id, _upload("image.png", image)))

    assert stored.upload.status == "approved"
    assert stored.upload.scan_status == "disabled"


def test_upload_records_full_storage_path(tmp_path: Path):
    store, website_id = _store(tmp_path)
    configured = replace(settings, project_root=tmp_path)
    manager = UploadManager(store, configured)
    manager._scan_for_malware = lambda path: None  # type: ignore[method-assign]
    image = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (320).to_bytes(4, "big") + (200).to_bytes(4, "big")

    stored = asyncio.run(manager.store_upload(website_id, _upload("map.png", image)))

    assert stored.upload.storage_path == configured.uploads_root / "active-site" / stored.upload.id / "content"


def test_upload_usage_only_protects_active_jobs(tmp_path: Path):
    store, website_id = _store(tmp_path)
    manager = UploadManager(store, replace(settings, project_root=tmp_path))
    job = store.create_job(website_id, "Use the image", "test-model", ("image-upload",))

    assert manager.upload_usage("image-upload", website_id) == ("a queued or running job",)
    assert store.claim_next_job(website_id) is not None
    assert manager.upload_usage("image-upload", website_id) == ("a queued or running job",)

    store.complete_job(job.id, status="failed")
    assert manager.upload_usage("image-upload", website_id) == ()


def test_scanner_unavailable_upload_can_be_rescanned(tmp_path: Path):
    store, website_id = _store(tmp_path)
    configured = replace(settings, project_root=tmp_path, max_upload_bytes=1024)
    manager = UploadManager(store, configured)
    image = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (320).to_bytes(4, "big") + (200).to_bytes(4, "big")

    def unavailable(_path: Path) -> None:
        raise UploadRejected("Malware scanner is unavailable; upload remains quarantined.")

    manager._scan_for_malware = unavailable  # type: ignore[method-assign]
    with pytest.raises(UploadRejected, match="scanner is unavailable"):
        asyncio.run(manager.store_upload(website_id, _upload("map.png", image)))

    rejected = store.list_uploads(website_id)[0]
    assert rejected.status == "rejected"
    assert (rejected.storage_path.parent / "quarantine.bin").is_file()

    manager._scan_for_malware = lambda path: None  # type: ignore[method-assign]
    rescanned = asyncio.run(manager.rescan_upload(website_id, rejected.id))
    assert rescanned.upload.status == "approved"
    assert rescanned.upload.storage_path.read_bytes() == image
