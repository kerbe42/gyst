"""SQLite layer for the Meals module."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

import config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.MEALS_DB_PATH)
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
    config.MEALS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _cursor() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meals (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              meal_date TEXT,
              meal_type TEXT,
              notes TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_meals_date ON meals(meal_date);

            CREATE TABLE IF NOT EXISTS recipes (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              ingredients TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        # Migration: ingredients column (JSON list of names).
        existing = {r[1] for r in conn.execute("PRAGMA table_info(meals)")}
        if "ingredients" not in existing:
            conn.execute("ALTER TABLE meals ADD COLUMN ingredients TEXT")


# ---- Recipes (user-added meal templates) -------------------------------------
def list_recipes() -> list[dict]:
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT id, name, ingredients, created_at FROM recipes "
            "ORDER BY name COLLATE NOCASE ASC"
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            raw = d.get("ingredients")
            if raw:
                try:
                    d["ingredients"] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d["ingredients"] = []
            else:
                d["ingredients"] = []
            out.append(d)
        return out


def add_recipe(name: str, ingredients: Optional[list[str]] = None) -> int:
    ing_json = json.dumps([i for i in (ingredients or []) if i])
    with _cursor() as conn:
        cur = conn.execute(
            "INSERT INTO recipes (name, ingredients) VALUES (?, ?)",
            (name.strip(), ing_json),
        )
        return int(cur.lastrowid)


def delete_recipe(recipe_id: int) -> None:
    with _cursor() as conn:
        conn.execute("DELETE FROM recipes WHERE id = ?", (int(recipe_id),))


def get_recipe_by_name(name: str) -> Optional[dict]:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT id, name, ingredients FROM recipes WHERE name = ?",
            (name.strip(),),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        raw = d.get("ingredients")
        try:
            d["ingredients"] = json.loads(raw) if raw else []
        except (json.JSONDecodeError, TypeError):
            d["ingredients"] = []
        return d


def list_meals(upcoming_only: bool = True) -> list[dict]:
    where = (
        "WHERE meal_date IS NULL OR meal_date >= date('now')"
        if upcoming_only
        else ""
    )
    with _cursor() as conn:
        rows = conn.execute(
            f"""
            SELECT id, name, meal_date, meal_type, notes, ingredients, created_at
            FROM meals
            {where}
            ORDER BY
              CASE WHEN meal_date IS NULL THEN 1 ELSE 0 END,
              meal_date ASC,
              created_at DESC
            """
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            raw = d.get("ingredients")
            if raw:
                try:
                    d["ingredients"] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d["ingredients"] = []
            else:
                d["ingredients"] = []
            out.append(d)
        return out


def add_meal(
    name: str,
    meal_date: Optional[str] = None,
    meal_type: Optional[str] = None,
    notes: Optional[str] = None,
    ingredients: Optional[list[str]] = None,
) -> int:
    ing_json = json.dumps([i for i in (ingredients or []) if i]) if ingredients else None
    with _cursor() as conn:
        cur = conn.execute(
            """
            INSERT INTO meals (name, meal_date, meal_type, notes, ingredients)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                meal_date,
                meal_type,
                (notes or "").strip() or None,
                ing_json,
            ),
        )
        return int(cur.lastrowid)


def delete_meal(meal_id: int) -> None:
    with _cursor() as conn:
        conn.execute("DELETE FROM meals WHERE id = ?", (int(meal_id),))


def upcoming_count() -> int:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM meals "
            "WHERE meal_date IS NULL OR meal_date >= date('now')"
        ).fetchone()
        return int(row["n"]) if row else 0
