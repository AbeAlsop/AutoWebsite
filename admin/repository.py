from __future__ import annotations

import sqlite3
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Website:
    id: int
    name: str
    github_repo: str
    working_directory: Path
    # An opaque reference to a deployment secret, never a raw GitHub token.
    github_token: str | None
    owner: str


@dataclass(frozen=True)
class Admin:
    username: str
    password_hash: str
    website_id: int


@dataclass(frozen=True)
class Job:
    id: str
    website_id: int
    prompt: str
    status: str
    created_at: int
    started_at: int | None
    completed_at: int | None
    agent_output: str | None
    error: str | None
    changed_files: tuple[str, ...]
    diff: str | None
    workspace_directory: Path | None
    model: str | None
    upload_ids: tuple[str, ...]


@dataclass(frozen=True)
class Upload:
    id: str
    website_id: int
    original_filename: str
    storage_path: Path
    checksum: str | None
    mime_type: str | None
    size: int | None
    width: int | None
    height: int | None
    scan_status: str
    status: str
    created_at: int
    error: str | None


class RepositoryConfigurationError(RuntimeError):
    """Raised when persistent configuration violates the single-site POC model."""


class RepositoryStore:
    """Persistent, server-side mapping from administrators to websites."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(
        self,
        *,
        bootstrap_username: str,
        bootstrap_password_hash: str,
        bootstrap_website_name: str,
        bootstrap_github_repo: str,
        bootstrap_working_directory: Path,
        bootstrap_github_token_ref: str | None,
    ) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS websites (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    github_repo TEXT NOT NULL,
                    working_directory TEXT NOT NULL,
                    github_token TEXT,
                    owner TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS admins (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    website_id INTEGER NOT NULL,
                    FOREIGN KEY (website_id) REFERENCES websites(id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    website_id INTEGER NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    started_at INTEGER,
                    completed_at INTEGER,
                    agent_output TEXT,
                    error TEXT,
                    changed_files TEXT NOT NULL DEFAULT '[]',
                    diff TEXT,
                    workspace_directory TEXT,
                    model TEXT,
                    upload_ids TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY (website_id) REFERENCES websites(id) ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS jobs_by_status_created_at
                    ON jobs(status, created_at);

                CREATE TABLE IF NOT EXISTS uploads (
                    id TEXT PRIMARY KEY,
                    website_id INTEGER NOT NULL,
                    original_filename TEXT NOT NULL,
                    storage_path TEXT,
                    checksum TEXT,
                    mime_type TEXT,
                    size INTEGER,
                    width INTEGER,
                    height INTEGER,
                    scan_status TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    error TEXT,
                    FOREIGN KEY (website_id) REFERENCES websites(id) ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS uploads_by_website_created_at
                    ON uploads(website_id, created_at DESC);
                """
            )
            job_columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
            if "upload_ids" not in job_columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN upload_ids TEXT NOT NULL DEFAULT '[]'")
            upload_columns = {row["name"] for row in connection.execute("PRAGMA table_info(uploads)")}
            if "storage_path" not in upload_columns:
                connection.execute("ALTER TABLE uploads ADD COLUMN storage_path TEXT")

            # The public site can be initialized without an admin password, while
            # authentication still requires an explicitly configured password hash.
            if self._website_count(connection) == 0:
                cursor = connection.execute(
                    """
                    INSERT INTO websites (name, github_repo, working_directory, github_token, owner)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        bootstrap_website_name,
                        bootstrap_github_repo,
                        str(bootstrap_working_directory.resolve()),
                        bootstrap_github_token_ref,
                        bootstrap_username,
                    ),
                )
                website_id = cursor.lastrowid
            else:
                website_id = self._single_website_id(connection)

            # Keep the Phase 3 environment-based setup as the first-deploy path.
            if bootstrap_password_hash and self._admin_count(connection) == 0:
                connection.execute(
                    """
                    INSERT INTO admins (username, password_hash, website_id)
                    VALUES (?, ?, ?)
                    """,
                    (bootstrap_username, bootstrap_password_hash, website_id),
                )

    def get_active_website(self) -> Website | None:
        """Return the sole configured website for the proof of concept."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, github_repo, working_directory, github_token, owner
                FROM websites ORDER BY id LIMIT 2
                """
            ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise RepositoryConfigurationError(
                "The single-site proof of concept requires exactly one website record."
            )
        return self._website_from_row(rows[0])

    def get_admin(self, username: str) -> Admin | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT username, password_hash, website_id FROM admins WHERE username = ?",
                (username,),
            ).fetchone()
        return None if row is None else Admin(**dict(row))

    def create_job(self, website_id: int, prompt: str, model: str, upload_ids: tuple[str, ...] = ()) -> Job:
        job_id = uuid.uuid4().hex
        created_at = int(time.time())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (id, website_id, prompt, status, created_at, model, upload_ids)
                VALUES (?, ?, ?, 'queued', ?, ?, ?)
                """,
                (job_id, website_id, prompt, created_at, model, json.dumps(upload_ids)),
            )
        job = self.get_job(job_id, website_id)
        if job is None:
            raise RepositoryConfigurationError("The newly created job could not be read.")
        return job

    def create_reprompt_job(
        self, job_id: str, website_id: int, prompt: str, model: str, upload_ids: tuple[str, ...]
    ) -> Job:
        """Replace an unapproved draft with a new job based on its private workspace."""
        next_job_id = uuid.uuid4().hex
        created_at = int(time.time())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """
                SELECT workspace_directory FROM jobs
                WHERE id = ? AND website_id = ? AND status = 'awaiting_review'
                """,
                (job_id, website_id),
            ).fetchone()
            if previous is None or previous["workspace_directory"] is None:
                connection.rollback()
                raise RepositoryConfigurationError("The draft is no longer available for editing.")
            connection.execute("UPDATE jobs SET status = 'superseded' WHERE id = ?", (job_id,))
            connection.execute(
                """
                INSERT INTO jobs (
                    id, website_id, prompt, status, created_at, model, upload_ids, workspace_directory
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)
                """,
                (
                    next_job_id,
                    website_id,
                    prompt,
                    created_at,
                    model,
                    json.dumps(upload_ids),
                    previous["workspace_directory"],
                ),
            )
            connection.commit()
        job = self.get_job(next_job_id, website_id)
        if job is None:
            raise RepositoryConfigurationError("The follow-up job could not be read.")
        return job

    def create_upload(
        self, upload_id: str, website_id: int, original_filename: str, storage_path: Path
    ) -> Upload:
        created_at = int(time.time())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO uploads (
                    id, website_id, original_filename, storage_path, scan_status, status, created_at
                ) VALUES (?, ?, ?, ?, 'pending', 'quarantined', ?)
                """,
                (upload_id, website_id, original_filename, str(storage_path), created_at),
            )
        upload = self.get_upload(upload_id, website_id)
        if upload is None:
            raise RepositoryConfigurationError("The newly created upload could not be read.")
        return upload

    def complete_upload(
        self,
        upload_id: str,
        website_id: int,
        *,
        checksum: str,
        mime_type: str,
        size: int,
        width: int | None,
        height: int | None,
        scan_status: str = "clean",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE uploads
                SET checksum = ?, mime_type = ?, size = ?, width = ?, height = ?,
                    scan_status = ?, status = 'approved', error = NULL
                WHERE id = ? AND website_id = ? AND status IN ('quarantined', 'rejected')
                """,
                (checksum, mime_type, size, width, height, scan_status, upload_id, website_id),
            )

    def reject_upload(self, upload_id: str, website_id: int, error: str, scan_status: str = "rejected") -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE uploads
                SET scan_status = ?, status = 'rejected', error = ?
                WHERE id = ? AND website_id = ? AND status = 'quarantined'
                """,
                (scan_status, error, upload_id, website_id),
            )

    def delete_upload(self, upload_id: str, website_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM uploads WHERE id = ? AND website_id = ?",
                (upload_id, website_id),
            )
        return cursor.rowcount == 1

    def get_upload(self, upload_id: str, website_id: int) -> Upload | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, website_id, original_filename, checksum, mime_type, size, width,
                       height, scan_status, status, created_at, error, storage_path
                FROM uploads WHERE id = ? AND website_id = ?
                """,
                (upload_id, website_id),
            ).fetchone()
        return None if row is None else self._upload_from_row(row)

    def list_uploads(self, website_id: int, limit: int = 20) -> list[Upload]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, website_id, original_filename, checksum, mime_type, size, width,
                       height, scan_status, status, created_at, error, storage_path
                FROM uploads WHERE website_id = ? ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (website_id, limit),
            ).fetchall()
        return [self._upload_from_row(row) for row in rows]

    def get_approved_uploads(self, website_id: int, upload_ids: tuple[str, ...]) -> list[Upload]:
        if not upload_ids:
            return []
        placeholders = ", ".join("?" for _ in upload_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, website_id, original_filename, checksum, mime_type, size, width,
                       height, scan_status, status, created_at, error, storage_path
                FROM uploads
                WHERE website_id = ? AND status = 'approved' AND id IN ({placeholders})
                """,
                (website_id, *upload_ids),
            ).fetchall()
        uploads = {row["id"]: self._upload_from_row(row) for row in rows}
        if len(uploads) != len(upload_ids):
            raise RepositoryConfigurationError("One or more selected uploads are unavailable.")
        return [uploads[upload_id] for upload_id in upload_ids]

    def get_job(self, job_id: str, website_id: int) -> Job | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, website_id, prompt, status, created_at, started_at, completed_at,
                       agent_output, error, changed_files, diff, workspace_directory, model, upload_ids
                FROM jobs WHERE id = ? AND website_id = ?
                """,
                (job_id, website_id),
            ).fetchone()
        return None if row is None else self._job_from_row(row)

    def list_jobs(self, website_id: int, limit: int = 20) -> list[Job]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, website_id, prompt, status, created_at, started_at, completed_at,
                       agent_output, error, changed_files, diff, workspace_directory, model, upload_ids
                FROM jobs WHERE website_id = ? ORDER BY created_at DESC LIMIT ?
                """,
                (website_id, limit),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def has_active_job_using_upload(self, website_id: int, upload_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM jobs
                WHERE website_id = ?
                  AND status IN ('queued', 'running', 'cancel_requested')
                  AND upload_ids LIKE ?
                LIMIT 1
                """,
                (website_id, f'%"{upload_id}"%'),
            ).fetchone()
        return row is not None

    def claim_next_job(self, website_id: int) -> Job | None:
        """Atomically claim one queued job, preserving single-site job serialization."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id FROM jobs
                WHERE website_id = ? AND status = 'queued'
                  AND NOT EXISTS (
                      SELECT 1 FROM jobs AS pending_review
                      WHERE pending_review.website_id = jobs.website_id
                        AND pending_review.status = 'awaiting_review'
                  )
                ORDER BY created_at ASC LIMIT 1
                """,
                (website_id,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            started_at = int(time.time())
            connection.execute(
                "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
                (started_at, row["id"]),
            )
            claimed = connection.execute(
                """
                SELECT id, website_id, prompt, status, created_at, started_at, completed_at,
                       agent_output, error, changed_files, diff, workspace_directory, model, upload_ids
                FROM jobs WHERE id = ?
                """,
                (row["id"],),
            ).fetchone()
            connection.commit()
        return self._job_from_row(claimed)

    def complete_job(
        self,
        job_id: str,
        *,
        status: str,
        agent_output: str | None = None,
        error: str | None = None,
        changed_files: list[str] | None = None,
        diff: str | None = None,
        workspace_directory: Path | None = None,
    ) -> None:
        if status not in {"awaiting_review", "failed", "cancelled"}:
            raise ValueError(f"Unsupported final job status: {status}")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, completed_at = ?, agent_output = ?, error = ?, changed_files = ?,
                    diff = ?, workspace_directory = ?
                WHERE id = ?
                """,
                (
                    status,
                    int(time.time()),
                    agent_output,
                    error,
                    json.dumps(changed_files or []),
                    diff,
                    None if workspace_directory is None else str(workspace_directory),
                    job_id,
                ),
            )

    def request_cancel(self, job_id: str, website_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = CASE WHEN status = 'running' THEN 'cancel_requested' ELSE 'cancelled' END,
                    completed_at = CASE WHEN status = 'queued' THEN ? ELSE completed_at END
                WHERE id = ? AND website_id = ? AND status IN ('queued', 'running')
                """,
                (int(time.time()), job_id, website_id),
            )
        return cursor.rowcount == 1

    def approve_job(self, job_id: str, website_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET status = 'approved'
                WHERE id = ? AND website_id = ? AND status = 'awaiting_review'
                """,
                (job_id, website_id),
            )
        return cursor.rowcount == 1

    def reject_job(self, job_id: str, website_id: int) -> bool:
        """Discard an unapproved workspace without changing the staging revision."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET status = 'rejected'
                WHERE id = ? AND website_id = ? AND status = 'awaiting_review'
                """,
                (job_id, website_id),
            )
        return cursor.rowcount == 1

    def recover_interrupted_jobs(self, website_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'failed', completed_at = ?,
                    error = 'The service restarted before this agent job completed.'
                WHERE website_id = ? AND status IN ('running', 'cancel_requested')
                """,
                (int(time.time()), website_id),
            )

    def get_website_for_admin(self, username: str, website_id: int | None = None) -> Website | None:
        """Return only the website assigned to this admin, never a client path."""
        query = """
            SELECT w.id, w.name, w.github_repo, w.working_directory, w.github_token, w.owner
            FROM websites AS w
            JOIN admins AS a ON a.website_id = w.id
            WHERE a.username = ?
        """
        parameters: tuple[object, ...] = (username,)
        if website_id is not None:
            query += " AND w.id = ?"
            parameters = (username, website_id)

        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        if row is None:
            return None
        return self._website_from_row(row)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _admin_count(connection: sqlite3.Connection) -> int:
        return int(connection.execute("SELECT COUNT(*) FROM admins").fetchone()[0])

    @staticmethod
    def _website_count(connection: sqlite3.Connection) -> int:
        return int(connection.execute("SELECT COUNT(*) FROM websites").fetchone()[0])

    @staticmethod
    def _single_website_id(connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT id FROM websites ORDER BY id LIMIT 1").fetchone()
        if row is None:
            raise RepositoryConfigurationError("No active website is configured.")
        return int(row[0])

    @staticmethod
    def _website_from_row(row: sqlite3.Row) -> Website:
        values = dict(row)
        values["working_directory"] = Path(values["working_directory"])
        return Website(**values)

    @staticmethod
    def _upload_from_row(row: sqlite3.Row) -> Upload:
        values = dict(row)
        values["storage_path"] = Path(values["storage_path"]) if values["storage_path"] else Path()
        return Upload(**values)

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> Job:
        values = dict(row)
        values["changed_files"] = tuple(json.loads(values["changed_files"]))
        values["upload_ids"] = tuple(json.loads(values["upload_ids"]))
        if values["workspace_directory"] is not None:
            values["workspace_directory"] = Path(values["workspace_directory"])
        return Job(**values)
