from __future__ import annotations

import sqlite3
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
                """
            )

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
