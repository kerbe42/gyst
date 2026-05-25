"""SQLite layer for the Announcements module."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

import config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.ANNOUNCEMENTS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _cursor() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    config.ANNOUNCEMENTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _cursor() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS announcements (
              id INTEGER PRIMARY KEY,
              title TEXT NOT NULL,
              body TEXT,
              posted_by INTEGER,
              pinned INTEGER NOT NULL DEFAULT 0,
              expires_at TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_ann_pinned ON announcements(pinned);
            CREATE INDEX IF NOT EXISTS idx_ann_created ON announcements(created_at);
            """
        )


def list_announcements(include_expired: bool = False) -> list[dict]:
    where = ""
    if not include_expired:
        where = (
            "WHERE expires_at IS NULL OR expires_at >= date('now')"
        )
    with _cursor() as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, body, posted_by, pinned, expires_at, created_at
            FROM announcements
            {where}
            ORDER BY pinned DESC, created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def add_announcement(
    title: str,
    body: Optional[str] = None,
    posted_by: Optional[int] = None,
    pinned: bool = False,
    expires_at: Optional[str] = None,
) -> int:
    with _cursor() as conn:
        cur = conn.execute(
            """
            INSERT INTO announcements (title, body, posted_by, pinned, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                (body or "").strip() or None,
                int(posted_by) if posted_by else None,
                1 if pinned else 0,
                expires_at,
            ),
        )
        return int(cur.lastrowid)


def delete_announcement(announcement_id: int) -> None:
    with _cursor() as conn:
        conn.execute(
            "DELETE FROM announcements WHERE id = ?", (int(announcement_id),)
        )


def toggle_pinned(announcement_id: int) -> None:
    with _cursor() as conn:
        conn.execute(
            "UPDATE announcements SET pinned = 1 - pinned WHERE id = ?",
            (int(announcement_id),),
        )


def open_count() -> int:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM announcements "
            "WHERE expires_at IS NULL OR expires_at >= date('now')"
        ).fetchone()
        return int(row["n"]) if row else 0
