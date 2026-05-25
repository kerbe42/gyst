"""SQLite layer for the Notes module.

Notes are free-form text snippets the household uses to jot down anything
that doesn't fit the other modules (recipes-in-progress, packing lists,
random reminders, etc.). Each note has a title, body, optional pin flag,
and timestamps. Pinned notes always sort first.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

import config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.NOTES_DB_PATH)
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
    config.NOTES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _cursor() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notes (
              id INTEGER PRIMARY KEY,
              title TEXT NOT NULL,
              body TEXT,
              author_id INTEGER,
              pinned INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_notes_pinned ON notes(pinned);
            CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at);

            -- JARVIS persistent memory: arbitrary key/value facts the
            -- assistant writes when it learns something about the
            -- household (preferences, recurring patterns, names of pets,
            -- etc.). Keys are short identifiers; values are free text.
            CREATE TABLE IF NOT EXISTS assistant_memory (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Throttle log so proactive pushes don't spam. One row per
            -- (kind, user_id) most-recently-fired-at.
            CREATE TABLE IF NOT EXISTS assistant_pushes (
              kind TEXT NOT NULL,
              user_id INTEGER NOT NULL,
              last_sent TEXT NOT NULL DEFAULT (datetime('now')),
              PRIMARY KEY (kind, user_id)
            );
            """
        )


def list_notes() -> list[dict]:
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT id, title, body, author_id, pinned, created_at, updated_at
            FROM notes
            ORDER BY pinned DESC, updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_note(note_id: int) -> Optional[dict]:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT id, title, body, author_id, pinned, created_at, updated_at "
            "FROM notes WHERE id = ?",
            (int(note_id),),
        ).fetchone()
        return dict(row) if row else None


def add_note(
    title: str,
    body: Optional[str] = None,
    author_id: Optional[int] = None,
    pinned: bool = False,
) -> int:
    with _cursor() as conn:
        cur = conn.execute(
            """
            INSERT INTO notes (title, body, author_id, pinned)
            VALUES (?, ?, ?, ?)
            """,
            (
                title.strip(),
                (body or "").strip() or None,
                int(author_id) if author_id else None,
                1 if pinned else 0,
            ),
        )
        return int(cur.lastrowid)


def update_note(
    note_id: int,
    *,
    title: Optional[str] = None,
    body: Optional[str] = None,
) -> None:
    """Update title and/or body. Always bumps `updated_at`."""
    sets: list[str] = []
    args: list = []
    if title is not None:
        sets.append("title = ?")
        args.append(title.strip())
    if body is not None:
        sets.append("body = ?")
        args.append((body or "").strip() or None)
    if not sets:
        return
    sets.append("updated_at = datetime('now')")
    args.append(int(note_id))
    with _cursor() as conn:
        conn.execute(
            f"UPDATE notes SET {', '.join(sets)} WHERE id = ?",
            tuple(args),
        )


def toggle_pinned(note_id: int) -> None:
    with _cursor() as conn:
        conn.execute(
            "UPDATE notes SET pinned = 1 - pinned, "
            "updated_at = datetime('now') WHERE id = ?",
            (int(note_id),),
        )


def delete_note(note_id: int) -> None:
    with _cursor() as conn:
        conn.execute("DELETE FROM notes WHERE id = ?", (int(note_id),))


# ---- Assistant memory --------------------------------------------------------
def memory_set(key: str, value: str) -> None:
    if not key or not key.strip():
        return
    with _cursor() as conn:
        conn.execute(
            """
            INSERT INTO assistant_memory (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = datetime('now')
            """,
            (key.strip()[:120], (value or "")[:2000]),
        )


def memory_get(key: str) -> Optional[str]:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT value FROM assistant_memory WHERE key = ?",
            (key.strip(),),
        ).fetchone()
        return row[0] if row else None


def memory_list(limit: int = 100) -> list[dict]:
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT key, value, updated_at FROM assistant_memory "
            "ORDER BY updated_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def memory_delete(key: str) -> None:
    with _cursor() as conn:
        conn.execute(
            "DELETE FROM assistant_memory WHERE key = ?", (key.strip(),),
        )


# ---- Proactive-push throttle log --------------------------------------------
def push_throttle_check(kind: str, user_id: int, cooldown_hours: float) -> bool:
    """Return True if it's been at least `cooldown_hours` since we last
    fired a proactive push of this kind to this user."""
    with _cursor() as conn:
        row = conn.execute(
            "SELECT last_sent FROM assistant_pushes "
            "WHERE kind = ? AND user_id = ?",
            (kind, int(user_id)),
        ).fetchone()
        if not row:
            return True
        from datetime import datetime, timedelta
        try:
            last = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return True
        return (datetime.now() - last) >= timedelta(hours=float(cooldown_hours))


def push_throttle_record(kind: str, user_id: int) -> None:
    with _cursor() as conn:
        conn.execute(
            """
            INSERT INTO assistant_pushes (kind, user_id)
            VALUES (?, ?)
            ON CONFLICT(kind, user_id) DO UPDATE SET
                last_sent = datetime('now')
            """,
            (kind, int(user_id)),
        )


def note_count() -> int:
    with _cursor() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM notes").fetchone()
        return int(row["n"]) if row else 0


def recent_notes(limit: int = 20) -> list[dict]:
    """Most recently created notes for the home-page activity feed."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT id, title, body, author_id, pinned, created_at, updated_at
              FROM notes
             ORDER BY created_at DESC, id DESC
             LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]

