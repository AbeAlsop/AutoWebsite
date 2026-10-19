"""Durable login budgets shared by workers and preserved across restarts."""

import hashlib
import math
import sqlite3
import time
from pathlib import Path


class LoginRateLimiter:
    def __init__(self, database: Path, *, window_seconds=300, account_limit=5,
                 ip_limit=20, global_limit=100):
        self.database = database
        self.window = window_seconds
        self.account_limit = account_limit
        self.ip_limit = ip_limit
        self.global_limit = global_limit

    def initialize(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS login_budgets (
                key TEXT PRIMARY KEY, started_at REAL NOT NULL, attempts INTEGER NOT NULL
            )""")

    def reserve(self, username: str | None, ip: str) -> int:
        """Reserve an attempt atomically; return Retry-After seconds if denied."""
        now = time.time()
        budgets = [("global", self.global_limit), (self._key("ip", ip), self.ip_limit)]
        if username is not None:
            budgets.append((self._key("account", username), self.account_limit))
        with sqlite3.connect(self.database, timeout=5) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM login_budgets WHERE started_at <= ?", (now - self.window,))
            retry_after = 0
            for key, limit in budgets:
                row = connection.execute(
                    "SELECT started_at, attempts FROM login_budgets WHERE key = ?", (key,)
                ).fetchone()
                if row and row[1] >= limit:
                    retry_after = max(retry_after, math.ceil(row[0] + self.window - now))
            if retry_after:
                return retry_after
            for key, _ in budgets:
                connection.execute("""INSERT INTO login_budgets VALUES (?, ?, 1)
                    ON CONFLICT(key) DO UPDATE SET attempts = attempts + 1""", (key, now))
        return 0

    @staticmethod
    def _key(kind: str, value: str) -> str:
        return kind + ":" + hashlib.sha256(value.encode("utf-8")).hexdigest()
