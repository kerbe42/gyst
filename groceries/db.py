"""SQLite layer for the Groceries module."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

import config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.GROCERIES_DB_PATH)
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
    config.GROCERIES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _cursor() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS groceries (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              quantity TEXT,
              notes TEXT,
              purchased INTEGER NOT NULL DEFAULT 0,
              added_by INTEGER,
              purchased_at TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_groc_purchased ON groceries(purchased);
            """
        )
        # Migration: optionally link a grocery row to the meal that needed it.
        existing = {r[1] for r in conn.execute("PRAGMA table_info(groceries)")}
        if "from_meal_id" not in existing:
            conn.execute(
                "ALTER TABLE groceries ADD COLUMN from_meal_id INTEGER"
            )


def list_groceries(include_purchased: bool = False) -> list[dict]:
    where = "" if include_purchased else "WHERE purchased = 0"
    with _cursor() as conn:
        rows = conn.execute(
            f"""
            SELECT id, name, quantity, notes, purchased, added_by,
                   purchased_at, created_at
            FROM groceries
            {where}
            ORDER BY purchased ASC, created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def add_grocery(
    name: str,
    quantity: Optional[str] = None,
    notes: Optional[str] = None,
    added_by: Optional[int] = None,
    from_meal_id: Optional[int] = None,
) -> int:
    with _cursor() as conn:
        cur = conn.execute(
            """
            INSERT INTO groceries (name, quantity, notes, added_by, from_meal_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                (quantity or "").strip() or None,
                (notes or "").strip() or None,
                int(added_by) if added_by else None,
                int(from_meal_id) if from_meal_id else None,
            ),
        )
        return int(cur.lastrowid)


def set_purchased(grocery_id: int, purchased: bool = True) -> None:
    with _cursor() as conn:
        if purchased:
            conn.execute(
                """
                UPDATE groceries
                   SET purchased = 1, purchased_at = datetime('now')
                 WHERE id = ?
                """,
                (int(grocery_id),),
            )
        else:
            conn.execute(
                """
                UPDATE groceries
                   SET purchased = 0, purchased_at = NULL
                 WHERE id = ?
                """,
                (int(grocery_id),),
            )


def delete_grocery(grocery_id: int) -> None:
    with _cursor() as conn:
        conn.execute("DELETE FROM groceries WHERE id = ?", (int(grocery_id),))


def clear_purchased() -> int:
    with _cursor() as conn:
        cur = conn.execute("DELETE FROM groceries WHERE purchased = 1")
        return int(cur.rowcount or 0)


def open_count() -> int:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM groceries WHERE purchased = 0"
        ).fetchone()
        return int(row["n"]) if row else 0


def recent_grocery_ticks(limit: int = 20) -> list[dict]:
    """Recently ticked-off (purchased) grocery items for the activity feed.
    Ordered by purchased_at DESC."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT id, name, quantity, purchased_at, added_by
              FROM groceries
             WHERE purchased = 1
               AND purchased_at IS NOT NULL
             ORDER BY purchased_at DESC, id DESC
             LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def low_stock_candidates(days: int = 14, limit: int = 10) -> list[dict]:
    """Items recently ticked off the grocery list (purchased in the last
    `days` days) that have NOT been re-added to the open list. These are
    "low-stock prompts" — staples the household consumed but hasn't put
    back on the shopping list.

    Match is by case-insensitive name. Returns most-recently-purchased first.
    """
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT g1.id, g1.name, g1.quantity, g1.purchased_at
              FROM groceries g1
             WHERE g1.purchased = 1
               AND g1.purchased_at IS NOT NULL
               AND g1.purchased_at >= datetime('now', ? || ' days')
               AND NOT EXISTS (
                   SELECT 1 FROM groceries g2
                    WHERE g2.purchased = 0
                      AND LOWER(g2.name) = LOWER(g1.name)
               )
             GROUP BY LOWER(g1.name)
             ORDER BY MAX(g1.purchased_at) DESC
             LIMIT ?
            """,
            (f"-{int(days)}", int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]

