from __future__ import annotations

import hashlib
import json
import os
import shlex
import struct
import subprocess
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from .config import Settings
from .repository import RepositoryStore, Upload

_CHUNK_BYTES = 64 * 1024
_SNIFF_BYTES = 64 * 1024
_IMAGE_MIME_TYPES = {"image/gif", "image/jpeg", "image/png", "image/webp"}


class UploadRejected(ValueError):
    """Raised when an upload cannot leave quarantine."""


@dataclass(frozen=True)
class StoredUpload:
    upload: Upload


class UploadManager:
    """Stores uploads by generated ID and approves them only after every check passes."""

    def __init__(self, store: RepositoryStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    def upload_usage(self, upload_id: str, website_id: int) -> tuple[str, ...]:
        if self.store.has_active_job_using_upload(website_id, upload_id):
            return ("a queued or running job",)
        return ()

    def delete_upload(self, website_id: int, upload_id: str) -> bool:
        upload = self.store.get_upload(upload_id, website_id)
        if upload is None:
            return False
        for path in (upload.storage_path, upload.storage_path.parent / "quarantine.bin", upload.storage_path.parent / "manifest.json"):
            if path.is_file() and not path.is_symlink():
                path.unlink()
        try:
            upload.storage_path.parent.rmdir()
        except OSError:
            pass
        deleted = self.store.delete_upload(upload_id, website_id)
        if deleted:
            self._write_gallery_manifest(website_id)
        return deleted

    async def store_upload(self, website_id: int, file: UploadFile) -> StoredUpload:
        if len(self.store.list_uploads(website_id, limit=self.settings.max_upload_count + 1)) >= self.settings.max_upload_count:
            await file.close()
            raise UploadRejected(f"Upload limit of {self.settings.max_upload_count} files reached.")
        upload_id = uuid.uuid4().hex
        original_filename = _display_filename(file.filename)
        upload_directory = self._upload_directory(upload_id)
        content_file = upload_directory / "content"
        upload = self.store.create_upload(upload_id, website_id, original_filename, content_file)
        upload_directory.mkdir(parents=True, mode=0o700)
        quarantined_file = upload_directory / "quarantine.bin"

        try:
            size, checksum, sniffed = await self._write_quarantined(file, quarantined_file)
            mime_type = _sniff_mime_type(sniffed)
            if mime_type is None:
                raise UploadRejected("The uploaded content type is not allowed.")
            width, height = _image_dimensions(mime_type, sniffed)
            scan_status = self._scan_status(quarantined_file)

            os.replace(quarantined_file, content_file)
            self.store.complete_upload(
                upload_id,
                website_id,
                checksum=checksum,
                mime_type=mime_type,
                size=size,
                width=width,
                height=height,
                scan_status=scan_status,
            )
            approved = self.store.get_upload(upload_id, website_id)
            if approved is None:
                raise RuntimeError("Approved upload could not be read.")
            self._write_manifest(approved)
            self._write_gallery_manifest(website_id)
            return StoredUpload(approved)
        except (UploadRejected, OSError) as error:
            if not _can_rescan(str(error)):
                quarantined_file.unlink(missing_ok=True)
            scan_status = "rejected" if isinstance(error, UploadRejected) else "error"
            self.store.reject_upload(upload_id, website_id, str(error), scan_status=scan_status)
            rejected = self.store.get_upload(upload_id, website_id)
            if rejected is not None:
                self._write_manifest(rejected)
            raise UploadRejected(str(error)) from error
        finally:
            await file.close()

    async def rescan_upload(self, website_id: int, upload_id: str) -> StoredUpload:
        upload = self.store.get_upload(upload_id, website_id)
        if upload is None or upload.status != "rejected" or not _can_rescan(upload.error or ""):
            raise UploadRejected("This upload is not eligible for malware rescan.")
        quarantined_file = upload.storage_path.parent / "quarantine.bin"
        if not quarantined_file.is_file() or quarantined_file.is_symlink():
            raise UploadRejected("The quarantined upload payload is unavailable.")
        payload = quarantined_file.read_bytes()
        mime_type = _sniff_mime_type(payload[:_SNIFF_BYTES])
        if mime_type is None:
            raise UploadRejected("The uploaded content type is not allowed.")
        width, height = _image_dimensions(mime_type, payload[:_SNIFF_BYTES])
        scan_status = self._scan_status(quarantined_file)
        os.replace(quarantined_file, upload.storage_path)
        self.store.complete_upload(
            upload_id,
            website_id,
            checksum=hashlib.sha256(payload).hexdigest(),
            mime_type=mime_type,
            size=len(payload),
            width=width,
            height=height,
            scan_status=scan_status,
        )
        approved = self.store.get_upload(upload_id, website_id)
        if approved is None:
            raise RuntimeError("Approved upload could not be read.")
        self._write_manifest(approved)
        self._write_gallery_manifest(website_id)
        return StoredUpload(approved)

    def _upload_directory(self, upload_id: str) -> Path:
        root = self.settings.uploads_root.resolve(strict=False)
        target = root / "active-site" / upload_id
        try:
            target.resolve(strict=False).relative_to(root)
        except ValueError as error:
            raise RuntimeError("Upload directory escapes the configured upload root.") from error
        return target

    async def _write_quarantined(self, file: UploadFile, destination: Path) -> tuple[int, str, bytes]:
        digest = hashlib.sha256()
        size = 0
        sniffed = bytearray()
        with destination.open("xb") as output:
            while chunk := await file.read(_CHUNK_BYTES):
                size += len(chunk)
                if size > self.settings.max_upload_bytes:
                    raise UploadRejected(f"Upload exceeds the {self.settings.max_upload_bytes}-byte limit.")
                digest.update(chunk)
                if len(sniffed) < _SNIFF_BYTES:
                    sniffed.extend(chunk[: _SNIFF_BYTES - len(sniffed)])
                output.write(chunk)
        if size == 0:
            raise UploadRejected("Empty uploads are not allowed.")
        return size, digest.hexdigest(), bytes(sniffed)

    def _scan_status(self, path: Path) -> str:
        if not self.settings.upload_malware_scan_enabled:
            return "disabled"
        self._scan_for_malware(path)
        return "clean"

    def _scan_for_malware(self, path: Path) -> None:
        command = shlex.split(self.settings.upload_malware_scan_command)
        if not command:
            raise UploadRejected("Malware scanning is not configured.")
        try:
            result = subprocess.run(
                [*command, str(path)], check=False, capture_output=True, text=True, timeout=60
            )
        except FileNotFoundError as error:
            raise UploadRejected("Malware scanner is unavailable; upload remains quarantined.") from error
        except subprocess.TimeoutExpired as error:
            raise UploadRejected("Malware scanner timed out; upload remains quarantined.") from error
        if result.returncode != 0:
            raise UploadRejected("Malware scan did not pass; upload remains quarantined.")

    def _write_manifest(self, upload: Upload) -> None:
        payload = {
            "schema_version": 1,
            "upload_id": upload.id,
            "original_filename": upload.original_filename,
            "checksum": upload.checksum,
            "mime_type": upload.mime_type,
            "size": upload.size,
            "width": upload.width,
            "height": upload.height,
            "scan_status": upload.scan_status,
            "status": upload.status,
        }
        _write_json(self._upload_directory(upload.id) / "manifest.json", payload)

    def _write_gallery_manifest(self, website_id: int) -> None:
        images = [upload for upload in self.store.list_uploads(website_id) if upload.status == "approved" and upload.mime_type in _IMAGE_MIME_TYPES]
        payload = {
            "schema_version": 1,
            "images": [
                {
                    "upload_id": upload.id,
                    "original_filename": upload.original_filename,
                    "checksum": upload.checksum,
                    "mime_type": upload.mime_type,
                    "width": upload.width,
                    "height": upload.height,
                }
                for upload in images
            ],
        }
        _write_json(self.settings.uploads_root / "active-site" / "gallery.json", payload)


def _display_filename(filename: str | None) -> str:
    candidate = unicodedata.normalize("NFC", (filename or "upload").replace("\\", "/").split("/")[-1])
    candidate = "".join(character for character in candidate if character.isprintable()).strip()
    return (candidate or "upload")[:255]


def _can_rescan(error: str) -> bool:
    return error in {
        "Malware scanner is unavailable; upload remains quarantined.",
        "Malware scanner timed out; upload remains quarantined.",
    }


def _sniff_mime_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _image_dimensions(mime_type: str, data: bytes) -> tuple[int | None, int | None]:
    if mime_type == "image/png" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if mime_type == "image/gif" and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if mime_type == "image/jpeg":
        return _jpeg_dimensions(data)
    if mime_type == "image/webp":
        return _webp_dimensions(data)
    return None, None


def _jpeg_dimensions(data: bytes) -> tuple[int | None, int | None]:
    offset = 2
    while offset + 9 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        while marker == 0xFF and offset < len(data):
            marker = data[offset]
            offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            break
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 2 or offset + length > len(data):
            break
        if 0xC0 <= marker <= 0xC3 or 0xC5 <= marker <= 0xC7 or 0xC9 <= marker <= 0xCB or 0xCD <= marker <= 0xCF:
            return int.from_bytes(data[offset + 5 : offset + 7], "big"), int.from_bytes(data[offset + 3 : offset + 5], "big")
        offset += length
    return None, None


def _webp_dimensions(data: bytes) -> tuple[int | None, int | None]:
    if len(data) < 16:
        return None, None
    chunk = data[12:16]
    if chunk == b"VP8X":
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        first, second, third, fourth = data[21:25]
        width = 1 + first + ((second & 0x3F) << 8)
        height = 1 + (second >> 6) + (third << 2) + ((fourth & 0x0F) << 10)
        return width, height
    return None, None


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
