"""SQLite layer for the Strongman module.

Stores the athlete's accumulated state — TM overrides, training log (set
logs), meal log, daily checks, bodyweight, and settings — that the standalone
app kept in localStorage. Single-athlete / household-shared (no per-user
scoping), matching GYST's other modules.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

import config

from . import data as sm_data


def _connect() -> sqlite3.Connection:
    # busy_timeout: JARVIS tool calls run on a worker thread and can write the
    # same DB concurrently with Reflex event handlers; without this a
    # simultaneous write raises "database is locked" instead of waiting.
    # WAL: readers don't block the writer, so the Progress page's reads don't
    # collide with a background meal/set log.
    conn = sqlite3.connect(config.STRONGMAN_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
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
    config.STRONGMAN_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _cursor() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
              key   TEXT PRIMARY KEY,
              value TEXT
            );

            CREATE TABLE IF NOT EXISTS tms (
              lift_id TEXT PRIMARY KEY,
              q1 INTEGER, q2 INTEGER, q3 INTEGER, q4 INTEGER
            );

            CREATE TABLE IF NOT EXISTS overrides (
              the_date    TEXT PRIMARY KEY,
              skipped     INTEGER NOT NULL DEFAULT 0,
              skip_reason TEXT,
              exercises   TEXT
            );

            CREATE TABLE IF NOT EXISTS training_log (
              id          INTEGER PRIMARY KEY,
              the_date    TEXT NOT NULL,
              exercise_id TEXT NOT NULL,
              set_num     INTEGER,
              weight_lb   REAL,
              reps        INTEGER,
              rpe         REAL,
              note        TEXT,
              created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_training_date ON training_log(the_date);

            CREATE TABLE IF NOT EXISTS meal_log (
              id          INTEGER PRIMARY KEY,
              the_date    TEXT NOT NULL,
              meal_id     TEXT,
              name        TEXT,
              multiplier  REAL NOT NULL DEFAULT 1,
              protein_g   REAL NOT NULL DEFAULT 0,
              kcal        REAL NOT NULL DEFAULT 0,
              created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_meal_date ON meal_log(the_date);

            CREATE TABLE IF NOT EXISTS daily_checks (
              the_date       TEXT PRIMARY KEY,
              water_l        REAL NOT NULL DEFAULT 0,
              creatine       INTEGER NOT NULL DEFAULT 0,
              flare_protocol INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS bodyweight_log (
              the_date TEXT PRIMARY KEY,
              lb       REAL NOT NULL
            );
            """
        )
        _migrate(conn)


# Bump this and add an `if version < N` block below whenever the schema
# changes. CREATE TABLE IF NOT EXISTS covers fresh installs; this covers
# existing installs where a new column must be ALTERed in — the sibling
# modules (chores/inventory/appointments) all carry the same guard because a
# fresh dev DB never reproduces the "old install, new column" break.
_SCHEMA_VERSION = 1


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= _SCHEMA_VERSION:
        return
    # (future) example:
    #   if version < 2:
    #       try:
    #           conn.execute("ALTER TABLE training_log ADD COLUMN tempo TEXT")
    #       except sqlite3.OperationalError:
    #           pass
    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


# ---- settings (KV) ---------------------------------------------------------
_SETTING_DEFAULTS = {
    "bodyweight_lb": sm_data.DEFAULT_BODYWEIGHT_LB,
    "kcal_target": None,
    "equipment": {"sandbag": False, "axle": False},
    "pinned_demos": {},
    "units": "lb",
    "meals_per_day": 2,
}


def _get_raw(conn, key: str):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row or row["value"] is None:
        return _SETTING_DEFAULTS.get(key)
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return _SETTING_DEFAULTS.get(key)


def get_settings() -> dict:
    with _cursor() as conn:
        out = {}
        for key in _SETTING_DEFAULTS:
            out[key] = _get_raw(conn, key)
        return out


def set_setting(key: str, value) -> None:
    with _cursor() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


def set_equipment(sandbag: bool, axle: bool) -> None:
    set_setting("equipment", {"sandbag": bool(sandbag), "axle": bool(axle)})


def set_pinned_demo(exercise_id: str, url: Optional[str]) -> None:
    with _cursor() as conn:
        demos = _get_raw(conn, "pinned_demos") or {}
        if url and url.strip():
            demos[exercise_id] = url.strip()
        else:
            demos.pop(exercise_id, None)
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('pinned_demos', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(demos),),
        )


# ---- training maxes --------------------------------------------------------
def get_tms() -> dict:
    """lift_id -> [q1, q2, q3, q4] (ints or None). Only rows with an override."""
    with _cursor() as conn:
        rows = conn.execute("SELECT lift_id, q1, q2, q3, q4 FROM tms").fetchall()
        return {r["lift_id"]: [r["q1"], r["q2"], r["q3"], r["q4"]] for r in rows}


def set_tm(lift_id: str, quarter: int, value: Optional[int]) -> None:
    col = f"q{int(quarter)}"
    if col not in ("q1", "q2", "q3", "q4"):
        raise ValueError(f"bad quarter {quarter}")
    with _cursor() as conn:
        conn.execute(
            f"INSERT INTO tms (lift_id, {col}) VALUES (?, ?) "
            f"ON CONFLICT(lift_id) DO UPDATE SET {col} = excluded.{col}",
            (lift_id, value),
        )
        # If every slot is now empty, drop the row so it falls back to the
        # suggestion formula.
        row = conn.execute(
            "SELECT q1, q2, q3, q4 FROM tms WHERE lift_id = ?", (lift_id,)
        ).fetchone()
        if row and all(row[c] is None for c in ("q1", "q2", "q3", "q4")):
            conn.execute("DELETE FROM tms WHERE lift_id = ?", (lift_id,))


# ---- per-day overrides -----------------------------------------------------
def get_override(the_date: str) -> Optional[dict]:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT skipped, skip_reason, exercises FROM overrides WHERE the_date = ?",
            (the_date,),
        ).fetchone()
        if not row:
            return None
        try:
            exercises = json.loads(row["exercises"]) if row["exercises"] else {}
        except (json.JSONDecodeError, TypeError):
            exercises = {}
        return {
            "skipped": bool(row["skipped"]),
            "skip_reason": row["skip_reason"],
            "exercises": exercises,
        }


def set_override(the_date: str, override: Optional[dict]) -> None:
    with _cursor() as conn:
        if override is None:
            conn.execute("DELETE FROM overrides WHERE the_date = ?", (the_date,))
            return
        conn.execute(
            "INSERT INTO overrides (the_date, skipped, skip_reason, exercises) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(the_date) DO UPDATE SET "
            "  skipped = excluded.skipped, skip_reason = excluded.skip_reason, "
            "  exercises = excluded.exercises",
            (
                the_date,
                1 if override.get("skipped") else 0,
                override.get("skip_reason"),
                json.dumps(override.get("exercises") or {}),
            ),
        )


def all_overrides() -> dict:
    with _cursor() as conn:
        rows = conn.execute("SELECT the_date FROM overrides").fetchall()
        return {r["the_date"]: get_override(r["the_date"]) for r in rows}


# ---- training log ----------------------------------------------------------
def list_sets(the_date: str, exercise_id: Optional[str] = None) -> list[dict]:
    where = "WHERE the_date = ?"
    params: list = [the_date]
    if exercise_id:
        where += " AND exercise_id = ?"
        params.append(exercise_id)
    with _cursor() as conn:
        rows = conn.execute(
            f"SELECT id, the_date, exercise_id, set_num, weight_lb, reps, rpe, note "
            f"FROM training_log {where} ORDER BY exercise_id, set_num",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def set_exercise_sets(the_date: str, exercise_id: str, sets: list[dict]) -> None:
    """Replace all logged sets for one exercise on a date. Each set dict:
    {set_num, weight_lb, reps, rpe, note}."""
    with _cursor() as conn:
        conn.execute(
            "DELETE FROM training_log WHERE the_date = ? AND exercise_id = ?",
            (the_date, exercise_id),
        )
        for s in sets:
            conn.execute(
                "INSERT INTO training_log (the_date, exercise_id, set_num, weight_lb, reps, rpe, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    the_date,
                    exercise_id,
                    s.get("set_num"),
                    s.get("weight_lb"),
                    s.get("reps"),
                    s.get("rpe"),
                    s.get("note"),
                ),
            )


def append_sets(the_date: str, exercise_id: str, sets: list[dict]) -> int:
    """Add sets for one exercise on a date WITHOUT deleting existing ones.
    Continues set_num from the current max. Returns the number appended.

    This is what voice/JARVIS logging must use: `set_exercise_sets` REPLACES
    (delete-then-insert) which is correct for the UI dialog that always submits
    the whole day's entry, but catastrophic for an append-style 'log another
    set' command — it would wipe every set logged earlier that day.
    """
    if not sets:
        return 0
    with _cursor() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(set_num), 0) AS m FROM training_log "
            "WHERE the_date = ? AND exercise_id = ?",
            (the_date, exercise_id),
        ).fetchone()
        base = int(row["m"])
        for i, s in enumerate(sets, start=1):
            conn.execute(
                "INSERT INTO training_log (the_date, exercise_id, set_num, weight_lb, reps, rpe, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    the_date,
                    exercise_id,
                    s.get("set_num") if s.get("set_num") is not None else base + i,
                    s.get("weight_lb"),
                    s.get("reps"),
                    s.get("rpe"),
                    s.get("note"),
                ),
            )
        return len(sets)


def top_sets(exercise_id: str) -> list[dict]:
    """Max logged weight per date for one exercise, oldest first (for charts)."""
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT the_date, MAX(weight_lb) AS top FROM training_log "
            "WHERE exercise_id = ? AND weight_lb IS NOT NULL "
            "GROUP BY the_date ORDER BY the_date",
            (exercise_id,),
        ).fetchall()
        return [{"date": r["the_date"], "weight_lb": r["top"]} for r in rows]


def logged_exercise_ids() -> list[str]:
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT DISTINCT exercise_id FROM training_log WHERE weight_lb IS NOT NULL"
        ).fetchall()
        return [r["exercise_id"] for r in rows]


# ---- meal log --------------------------------------------------------------
def list_meals(the_date: str) -> list[dict]:
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT id, meal_id, name, multiplier, protein_g, kcal "
            "FROM meal_log WHERE the_date = ? ORDER BY id",
            (the_date,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_meal(the_date: str, meal_id: str, name: str, protein_g: float, kcal: float, multiplier: float = 1) -> int:
    with _cursor() as conn:
        cur = conn.execute(
            "INSERT INTO meal_log (the_date, meal_id, name, multiplier, protein_g, kcal) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (the_date, meal_id, name, multiplier, protein_g, kcal),
        )
        return int(cur.lastrowid)


def remove_meal(meal_log_id: int) -> None:
    with _cursor() as conn:
        conn.execute("DELETE FROM meal_log WHERE id = ?", (int(meal_log_id),))


def meal_totals(the_date: str) -> dict:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(protein_g), 0) AS p, COALESCE(SUM(kcal), 0) AS k "
            "FROM meal_log WHERE the_date = ?",
            (the_date,),
        ).fetchone()
        return {"protein_g": row["p"], "kcal": row["k"]}


def meal_totals_by_date() -> dict[str, dict]:
    """{the_date: {protein_g, kcal}} for every logged day, in ONE query — for
    the Progress page's weekly-average chart, which otherwise did an N+1
    (one fresh connection per logged date)."""
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT the_date, COALESCE(SUM(protein_g), 0) AS p, COALESCE(SUM(kcal), 0) AS k "
            "FROM meal_log GROUP BY the_date"
        ).fetchall()
        return {r["the_date"]: {"protein_g": r["p"], "kcal": r["k"]} for r in rows}


# ---- daily checks ----------------------------------------------------------
def get_checks(the_date: str) -> dict:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT water_l, creatine, flare_protocol FROM daily_checks WHERE the_date = ?",
            (the_date,),
        ).fetchone()
        if not row:
            return {"water_l": 0.0, "creatine": False, "flare_protocol": False}
        return {
            "water_l": row["water_l"],
            "creatine": bool(row["creatine"]),
            "flare_protocol": bool(row["flare_protocol"]),
        }


def set_checks(the_date: str, **patch) -> None:
    # Read-modify-write in ONE connection/transaction so two near-simultaneous
    # updates (e.g. a water tap and a creatine toggle) can't clobber each
    # other's unrelated fields (lost-update race).
    with _cursor() as conn:
        row = conn.execute(
            "SELECT water_l, creatine, flare_protocol FROM daily_checks WHERE the_date = ?",
            (the_date,),
        ).fetchone()
        current = {
            "water_l": row["water_l"] if row else 0.0,
            "creatine": bool(row["creatine"]) if row else False,
            "flare_protocol": bool(row["flare_protocol"]) if row else False,
        }
        current.update(patch)
        conn.execute(
            "INSERT INTO daily_checks (the_date, water_l, creatine, flare_protocol) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(the_date) DO UPDATE SET "
            "  water_l = excluded.water_l, creatine = excluded.creatine, "
            "  flare_protocol = excluded.flare_protocol",
            (
                the_date,
                float(current["water_l"]),
                1 if current["creatine"] else 0,
                1 if current["flare_protocol"] else 0,
            ),
        )


# ---- bodyweight ------------------------------------------------------------
def set_bodyweight(the_date: str, lb: float) -> None:
    with _cursor() as conn:
        conn.execute(
            "INSERT INTO bodyweight_log (the_date, lb) VALUES (?, ?) "
            "ON CONFLICT(the_date) DO UPDATE SET lb = excluded.lb",
            (the_date, float(lb)),
        )


def list_bodyweight() -> list[dict]:
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT the_date, lb FROM bodyweight_log ORDER BY the_date"
        ).fetchall()
        return [{"date": r["the_date"], "lb": r["lb"]} for r in rows]


# ---- engine state assembler ------------------------------------------------
def engine_state() -> dict:
    """The slice the engine needs: TM overrides + owned equipment."""
    s = get_settings()
    return {"tms": get_tms(), "equipment": s["equipment"]}


# ---- reset (with backup) ---------------------------------------------------
def reset_all(backup: bool = True) -> Optional[str]:
    """Wipe all strongman data. Takes a timestamped copy first (unless
    disabled) so a mis-fire is recoverable, and truncates tables in one
    connection rather than unlinking the live file — unlink can race an open
    JARVIS connection mid-write and leave a half-open handle. Returns the
    backup path (or None)."""
    import shutil
    from datetime import datetime, timezone

    path = config.STRONGMAN_DB_PATH
    backup_path = None
    if backup and path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_path = str(path) + f".bak-{stamp}"
        try:
            shutil.copy2(path, backup_path)
        except Exception:
            backup_path = None
    with _cursor() as conn:
        for tbl in ("settings", "tms", "overrides", "training_log",
                    "meal_log", "daily_checks", "bodyweight_log"):
            conn.execute(f"DELETE FROM {tbl}")
    return backup_path
