"""SQLite layer for the Appointments module."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

import config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.APPOINTMENTS_DB_PATH)
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
    config.APPOINTMENTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _cursor() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS appointments (
              id INTEGER PRIMARY KEY,
              title TEXT NOT NULL,
              appointment_at TEXT NOT NULL,
              location TEXT,
              notes TEXT,
              for_person INTEGER,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_appt_when ON appointments(appointment_at);
            """
        )
        # Recurrence + parent-link migrations (mirrors chores tasks).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(appointments)")}
        if "recurrence" not in cols:
            conn.execute(
                "ALTER TABLE appointments ADD COLUMN recurrence TEXT"
            )
        if "parent_appointment_id" not in cols:
            conn.execute(
                "ALTER TABLE appointments ADD COLUMN "
                "parent_appointment_id INTEGER"
            )


def list_appointments(upcoming_only: bool = True) -> list[dict]:
    where = "WHERE appointment_at >= datetime('now')" if upcoming_only else ""
    with _cursor() as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, appointment_at, location, notes,
                   for_person, created_at, recurrence, parent_appointment_id
            FROM appointments
            {where}
            ORDER BY appointment_at ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_appointment(appointment_id: int) -> Optional[dict]:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT * FROM appointments WHERE id = ?",
            (int(appointment_id),),
        ).fetchone()
        return dict(row) if row else None


def add_appointment(
    title: str,
    appointment_at: str,  # ISO datetime, e.g. "2026-05-15 14:30"
    location: Optional[str] = None,
    notes: Optional[str] = None,
    for_person: Optional[int] = None,
    recurrence: Optional[str] = None,
    parent_appointment_id: Optional[int] = None,
) -> int:
    with _cursor() as conn:
        cur = conn.execute(
            """
            INSERT INTO appointments
                (title, appointment_at, location, notes, for_person,
                 recurrence, parent_appointment_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                appointment_at,
                (location or "").strip() or None,
                (notes or "").strip() or None,
                int(for_person) if for_person else None,
                (recurrence or "").strip() or None,
                int(parent_appointment_id) if parent_appointment_id else None,
            ),
        )
        return int(cur.lastrowid)


def delete_appointment(appointment_id: int) -> None:
    with _cursor() as conn:
        conn.execute(
            "DELETE FROM appointments WHERE id = ?", (int(appointment_id),)
        )


def advance_recurrence(appointment_id: int) -> Optional[int]:
    """If `appointment_id` carries a recurrence rule and its `appointment_at`
    has passed, create the next instance and return its new id. Called by
    the reminder dispatcher so a repeating appointment auto-rolls forward
    without an explicit 'mark done' click."""
    from datetime import datetime
    # Lazy import to avoid a chores->appointments cycle.
    from chores.db import _next_due_date

    appt = get_appointment(int(appointment_id))
    if not appt:
        return None
    rule = (appt.get("recurrence") or "").strip()
    if not rule:
        return None
    try:
        when = datetime.strptime(
            appt["appointment_at"], "%Y-%m-%d %H:%M:%S",
        )
    except (KeyError, ValueError):
        return None
    if when > datetime.now():
        return None  # original hasn't happened yet
    next_date = _next_due_date(rule, when.date().isoformat())
    if not next_date:
        return None
    # Preserve time-of-day.
    next_when = f"{next_date} {when.strftime('%H:%M:%S')}"
    # Avoid duplicates: check whether we've already materialized this one.
    with _cursor() as conn:
        existing = conn.execute(
            """
            SELECT id FROM appointments
            WHERE parent_appointment_id = ?
              AND appointment_at = ?
            """,
            (
                appt.get("parent_appointment_id") or appt["id"],
                next_when,
            ),
        ).fetchone()
        if existing:
            return None
    return add_appointment(
        title=appt["title"],
        appointment_at=next_when,
        location=appt.get("location"),
        notes=appt.get("notes"),
        for_person=appt.get("for_person"),
        recurrence=rule,
        parent_appointment_id=(
            appt.get("parent_appointment_id") or appt["id"]
        ),
    )


def upcoming_count() -> int:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM appointments "
            "WHERE appointment_at >= datetime('now')"
        ).fetchone()
        return int(row["n"]) if row else 0
