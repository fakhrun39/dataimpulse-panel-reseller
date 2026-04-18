"""
database.py — SQLite persistence layer for config, token cache, and audit logs.
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("di-panel.db")
DB_PATH = Path("panel.db")


class Database:
    def __init__(self):
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS config (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         TEXT    NOT NULL,
                    level      TEXT    NOT NULL DEFAULT 'INFO',
                    endpoint   TEXT    NOT NULL,
                    method     TEXT    NOT NULL,
                    status     INTEGER,
                    duration_ms INTEGER,
                    detail     TEXT
                );

                -- Default config rows (won't overwrite existing)
                INSERT OR IGNORE INTO config (key, value) VALUES
                    ('login',         ''),
                    ('password',      ''),
                    ('token',         ''),
                    ('token_expires', ''),
                    ('base_url',      'https://proxy.bbproject.myd.id');
            """)
        log.info("Database initialised at %s", DB_PATH)

    # ── Config ────────────────────────────────────────────────────────────────
    def get_config(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM config").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def set_config(self, key: str, value: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, value),
            )
        log.debug("Config set: %s", key)

    # ── Audit log ─────────────────────────────────────────────────────────────
    def log_request(
        self,
        endpoint: str,
        method: str,
        status: int = None,
        duration_ms: int = None,
        detail: str = None,
        level: str = "INFO",
    ):
        ts = datetime.utcnow().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO audit_log (ts, level, endpoint, method, status, duration_ms, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (ts, level, endpoint, method, status, duration_ms, detail),
            )

    def get_logs(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
