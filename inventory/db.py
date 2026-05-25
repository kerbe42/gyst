"""SQLite layer for the house-inventory app.

Two tables:
  - photos: one row per photo taken
  - items: one row per recognized item *sighting* (not per unique item)

The same physical drill recognized in three different photos = three rows.
"Where is my drill?" returns the most recent sighting.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

import config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_schema_ready = False

def _ensure_schema() -> None:
    """Lazily run init_db once per process so query helpers can be
    called from rx.var bodies (which fire at page compile time, before
    any on_load event handler runs)."""
    global _schema_ready
    if _schema_ready:
        return
    _schema_ready = True  # set first so init_db can call _cursor()
    try:
        init_db()
    except Exception:
        _schema_ready = False
        raise


@contextmanager
def _cursor() -> Iterator[sqlite3.Connection]:
    _ensure_schema()
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist. Idempotent. Also runs in-place
    migrations for columns added after the initial schema."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _cursor() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS photos (
              id INTEGER PRIMARY KEY,
              path TEXT NOT NULL,
              room TEXT NOT NULL,
              taken_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS items (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              category TEXT,
              quantity INTEGER NOT NULL DEFAULT 1,
              detector_count INTEGER,
              photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS rooms (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
            CREATE INDEX IF NOT EXISTS idx_items_photo ON items(photo_id);
            CREATE INDEX IF NOT EXISTS idx_rooms_sort ON rooms(sort_order);

            CREATE TABLE IF NOT EXISTS item_history (
              id INTEGER PRIMARY KEY,
              item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
              ts TEXT NOT NULL DEFAULT (datetime('now')),
              actor_name TEXT,
              kind TEXT NOT NULL,
              detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_item_history_item_id
                ON item_history(item_id, ts DESC);
            """
        )

        # Migrations on items.
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
        if "boxes" not in existing_cols:
            conn.execute("ALTER TABLE items ADD COLUMN boxes TEXT")
        if "for_sale" not in existing_cols:
            conn.execute(
                "ALTER TABLE items ADD COLUMN for_sale INTEGER NOT NULL DEFAULT 0"
            )
        if "estimated_value" not in existing_cols:
            # USD, nullable. NULL means 'unknown', distinct from 0 ('worthless').
            conn.execute("ALTER TABLE items ADD COLUMN estimated_value REAL")
        if "deleted_at" not in existing_cols:
            # Soft delete: NULL = active, timestamp = in trash. Search/Browse
            # filter out non-NULL; the Trash page shows only non-NULL.
            conn.execute("ALTER TABLE items ADD COLUMN deleted_at TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_deleted_at "
                "ON items(deleted_at)"
            )
        # Expiration tracking for food / meds / batteries.
        if "expires_at" not in existing_cols:
            conn.execute("ALTER TABLE items ADD COLUMN expires_at TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_expires "
                "ON items(expires_at)"
            )
        # Loan tracking: who borrowed this and when.
        if "loaned_to_id" not in existing_cols:
            conn.execute(
                "ALTER TABLE items ADD COLUMN loaned_to_id INTEGER"
            )
        if "loaned_to_name" not in existing_cols:
            conn.execute(
                "ALTER TABLE items ADD COLUMN loaned_to_name TEXT"
            )
        if "loaned_at" not in existing_cols:
            conn.execute("ALTER TABLE items ADD COLUMN loaned_at TEXT")
        if "loan_notes" not in existing_cols:
            conn.execute("ALTER TABLE items ADD COLUMN loan_notes TEXT")

        # Purchase / warranty / return-window tracking.
        try:
            conn.execute("ALTER TABLE items ADD COLUMN purchase_date TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE items ADD COLUMN purchase_price REAL")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE items ADD COLUMN purchase_store TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE items ADD COLUMN return_until TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE items ADD COLUMN warranty_until TEXT")
        except sqlite3.OperationalError:
            pass

        # Seed rooms from config.ROOMS on first run (only if table is empty).
        row = conn.execute("SELECT COUNT(*) AS n FROM rooms").fetchone()
        if int(row["n"]) == 0:
            conn.executemany(
                "INSERT INTO rooms (name, sort_order) VALUES (?, ?)",
                [(r, i) for i, r in enumerate(config.ROOMS)],
            )


# ---- Rooms -------------------------------------------------------------------
def list_rooms() -> list[dict]:
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT id, name, sort_order, created_at FROM rooms "
            "ORDER BY sort_order, name"
        ).fetchall()
        return [dict(r) for r in rows]


def bulk_move_room(from_room: str, to_room: str) -> int:
    """Move every item currently in `from_room` into `to_room` by
    rewriting the room column on the underlying photo rows. Returns
    the number of items whose effective room changed.

    Both rooms are matched case-insensitively. If `to_room` is not a
    known room, it is created on the fly so JARVIS doesn't have to
    do a two-step.
    """
    _ensure_schema()
    fr = (from_room or "").strip().lower()
    to = (to_room or "").strip().lower()
    if not fr or not to or fr == to:
        return 0
    with _cursor() as conn:
        existing = {r["name"].lower() for r in conn.execute(
            "SELECT name FROM rooms"
        ).fetchall()}
        if to not in existing:
            conn.execute(
                "INSERT INTO rooms (name, sort_order) "
                "VALUES (?, COALESCE((SELECT MAX(sort_order)+1 FROM rooms), 0))",
                (to,),
            )
        # Count items being moved BEFORE the update (the JOIN goes away
        # post-update because no photos point at `fr` anymore).
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM items "
            "JOIN photos ON items.photo_id = photos.id "
            "WHERE LOWER(photos.room) = ? AND items.deleted_at IS NULL",
            (fr,),
        ).fetchone()["n"]
        conn.execute(
            "UPDATE photos SET room = ? WHERE LOWER(room) = ?",
            (to, fr),
        )
    return int(n)


def move_item_to_room(item_id: int, target_room: str) -> None:
    """Move a single item to `target_room`. If the item's photo is
    shared with other items, we clone the photo row (same path,
    new room) and re-point this item only. Creates the target room
    if it doesn't exist."""
    _ensure_schema()
    target = (target_room or "").strip().lower()
    if not target:
        raise ValueError("target_room required")
    with _cursor() as conn:
        row = conn.execute(
            "SELECT photos.id AS photo_id, photos.path AS path, photos.room AS room "
            "FROM items JOIN photos ON items.photo_id = photos.id "
            "WHERE items.id = ?",
            (int(item_id),),
        ).fetchone()
        if not row:
            return
        if (row["room"] or "").lower() == target:
            return  # already there

        existing = {r["name"].lower() for r in conn.execute(
            "SELECT name FROM rooms"
        ).fetchall()}
        if target not in existing:
            conn.execute(
                "INSERT INTO rooms (name, sort_order) "
                "VALUES (?, COALESCE((SELECT MAX(sort_order)+1 FROM rooms), 0))",
                (target,),
            )

        share_count = conn.execute(
            "SELECT COUNT(*) AS n FROM items WHERE photo_id = ?",
            (row["photo_id"],),
        ).fetchone()["n"]

        if int(share_count) <= 1:
            # Sole occupant — flip the photo row's room in place.
            conn.execute(
                "UPDATE photos SET room = ? WHERE id = ?",
                (target, row["photo_id"]),
            )
        else:
            # Multi-item photo — clone the photo row and re-point this
            # item to the clone so the others stay in the source room.
            cur = conn.execute(
                "INSERT INTO photos (path, room) VALUES (?, ?)",
                (row["path"], target),
            )
            new_photo_id = int(cur.lastrowid)
            conn.execute(
                "UPDATE items SET photo_id = ? WHERE id = ?",
                (new_photo_id, int(item_id)),
            )


def list_room_names() -> list[str]:
    """Just the names, in sort order. Used for dropdowns."""
    return [r["name"] for r in list_rooms()]


def add_room(name: str) -> int:
    with _cursor() as conn:
        # Place new rooms at the end by default.
        max_row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM rooms"
        ).fetchone()
        next_order = int(max_row["m"]) + 1
        cur = conn.execute(
            "INSERT INTO rooms (name, sort_order) VALUES (?, ?)",
            (name.strip().lower(), next_order),
        )
        return int(cur.lastrowid)


def update_room(room_id: int, name: str, sort_order: int) -> None:
    with _cursor() as conn:
        conn.execute(
            "UPDATE rooms SET name = ?, sort_order = ? WHERE id = ?",
            (name.strip().lower(), int(sort_order), int(room_id)),
        )


def delete_room(room_id: int) -> None:
    """Delete a room. Note: existing photos/items referencing this room by
    name string are NOT updated — they keep working but won't appear in
    Browse's room dropdown unless the room name is recreated.
    """
    with _cursor() as conn:
        conn.execute("DELETE FROM rooms WHERE id = ?", (int(room_id),))


def save_photo(path: str, room: str) -> int:
    """Insert a photo row, return its id."""
    with _cursor() as conn:
        cur = conn.execute(
            "INSERT INTO photos (path, room) VALUES (?, ?)",
            (path, room),
        )
        return int(cur.lastrowid)


# ---- Item history -----------------------------------------------------------
def log_item_event(
    item_id: int,
    kind: str,
    detail=None,
    actor_name: Optional[str] = None,
) -> None:
    """Append an audit-trail row for an item. `detail` may be a dict (JSON-
    encoded) or a short string. Silently no-ops on error so history failures
    never break the actual mutation."""
    if not item_id or not kind:
        return
    if detail is not None and not isinstance(detail, str):
        try:
            detail = json.dumps(detail)
        except (TypeError, ValueError):
            detail = str(detail)
    try:
        with _cursor() as conn:
            conn.execute(
                "INSERT INTO item_history (item_id, kind, detail, actor_name)"
                " VALUES (?, ?, ?, ?)",
                (int(item_id), kind, detail, (actor_name or None)),
            )
    except Exception:
        pass


def item_history(item_id: int, limit: int = 50) -> list[dict]:
    """Return a chronological (newest-first) audit log for an item."""
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT id, item_id, ts, actor_name, kind, detail"
            "  FROM item_history WHERE item_id = ?"
            "  ORDER BY ts DESC, id DESC LIMIT ?",
            (int(item_id), int(limit)),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            raw = d.get("detail")
            if raw and isinstance(raw, str) and raw.startswith(("{", "[")):
                try:
                    d["detail_obj"] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d["detail_obj"] = None
            else:
                d["detail_obj"] = None
            out.append(d)
        return out


def save_items(photo_id: int, items: list[dict], actor_name: Optional[str] = None) -> list[int]:
    """Bulk-insert item sightings tied to a photo. Returns the new row IDs
    in the same order as `items` so callers can offer per-row actions
    (delete, edit) without re-querying.

    Each dict needs `name`. Optional: `category`, `quantity`, `detector_count`,
    `boxes`, `for_sale` (bool), `estimated_value` (USD float or None).
    """
    if not items:
        return []
    new_ids: list[int] = []
    with _cursor() as conn:
        for i in items:
            cur = conn.execute(
                """
                INSERT INTO items
                    (name, category, quantity, detector_count, boxes,
                     for_sale, estimated_value, photo_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    i["name"],
                    i.get("category", "other"),
                    int(i.get("quantity", 1)),
                    i.get("detector_count"),
                    json.dumps(i.get("boxes") or []),
                    1 if i.get("for_sale") else 0,
                    _coerce_value(i.get("estimated_value")),
                    photo_id,
                ),
            )
            new_ids.append(int(cur.lastrowid))
    # History log — outside the cursor so a logging failure can't roll back
    # the actual save.
    try:
        room = None
        with _cursor() as conn:
            row = conn.execute(
                "SELECT room FROM photos WHERE id = ?", (int(photo_id),)
            ).fetchone()
            if row:
                room = row["room"]
        for new_id, i in zip(new_ids, items):
            log_item_event(
                new_id,
                "created",
                detail={
                    "name": i.get("name"),
                    "qty": int(i.get("quantity", 1)),
                    "room": room,
                },
                actor_name=actor_name,
            )
    except Exception:
        pass
    return new_ids


def _coerce_value(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return f if f >= 0 else None
    except (TypeError, ValueError):
        return None


def _row_to_item(row: sqlite3.Row) -> dict:
    """Convert a sqlite Row to a plain dict, parsing the boxes JSON."""
    d = dict(row)
    boxes_raw = d.get("boxes")
    if boxes_raw:
        try:
            d["boxes"] = json.loads(boxes_raw)
        except (json.JSONDecodeError, TypeError):
            d["boxes"] = []
    else:
        d["boxes"] = []
    return d


def search_items(query: str, limit: int = 50) -> list[dict]:
    """Case-insensitive substring search on item name. Excludes soft-deleted."""
    pattern = f"%{query.lower().strip()}%"
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT items.id, items.name, items.category, items.quantity,
                   items.detector_count, items.boxes,
                   items.for_sale, items.estimated_value, items.created_at,
                   photos.path AS photo_path, photos.room
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE LOWER(items.name) LIKE ?
              AND items.deleted_at IS NULL
            ORDER BY items.created_at DESC
            LIMIT ?
            """,
            (pattern, limit),
        ).fetchall()
        return [_row_to_item(r) for r in rows]


def items_in_room(room: str) -> list[dict]:
    """All active item sightings in a given room."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT items.id, items.name, items.category, items.quantity,
                   items.detector_count, items.boxes,
                   items.for_sale, items.estimated_value, items.created_at,
                   photos.id AS photo_id, photos.path AS photo_path,
                   photos.taken_at AS photo_taken_at,
                   photos.room AS room
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE photos.room = ?
              AND items.deleted_at IS NULL
            ORDER BY photos.taken_at DESC, items.id ASC
            """,
            (room,),
        ).fetchall()
        return [_row_to_item(r) for r in rows]


def all_items() -> list[dict]:
    """All active item sightings across every room."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT items.id, items.name, items.category, items.quantity,
                   items.detector_count, items.boxes,
                   items.for_sale, items.estimated_value, items.created_at,
                   photos.id AS photo_id, photos.path AS photo_path,
                   photos.taken_at AS photo_taken_at,
                   photos.room AS room
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE items.deleted_at IS NULL
            ORDER BY photos.taken_at DESC, items.id ASC
            """
        ).fetchall()
        return [_row_to_item(r) for r in rows]


def list_deleted_items() -> list[dict]:
    """All soft-deleted items, most recently deleted first."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT items.id, items.name, items.category, items.quantity,
                   items.detector_count, items.boxes,
                   items.for_sale, items.estimated_value,
                   items.created_at, items.deleted_at,
                   photos.path AS photo_path, photos.room,
                   photos.taken_at AS photo_taken_at
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE items.deleted_at IS NOT NULL
            ORDER BY items.deleted_at DESC
            """
        ).fetchall()
        return [_row_to_item(r) for r in rows]


def latest_sighting(name_query: str) -> Optional[dict]:
    """Most recent sighting matching `name_query` (substring)."""
    rows = search_items(name_query, limit=1)
    return rows[0] if rows else None


def all_rooms_with_counts() -> list[tuple[str, int]]:
    """List of (room, active_item_count). Soft-deleted items aren't counted."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT photos.room, COUNT(items.id) AS n
            FROM photos
            LEFT JOIN items
                   ON items.photo_id = photos.id
                  AND items.deleted_at IS NULL
            GROUP BY photos.room
            ORDER BY n DESC, photos.room ASC
            """
        ).fetchall()
        return [(r["room"], int(r["n"])) for r in rows]


# ---- Expiration tracking -----------------------------------------------------
def set_expires_at(
    item_id: int,
    expires_at: Optional[str],
    actor_name: Optional[str] = None,
) -> None:
    """Set or clear the expiration date for an item. Stored as 'YYYY-MM-DD'."""
    value = (expires_at or "").strip() or None
    with _cursor() as conn:
        conn.execute(
            "UPDATE items SET expires_at = ? WHERE id = ?",
            (value, int(item_id)),
        )
    log_item_event(item_id, "expires", detail=value or "(cleared)",
                   actor_name=actor_name)


def items_expiring_within(days: int) -> list[dict]:
    """Active items whose expiry date is between today and today+N inclusive.
    Used by the reminder dispatcher to fire push notifications."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT items.id, items.name, items.category, items.quantity,
                   items.expires_at, items.photo_id,
                   photos.room AS room
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE items.deleted_at IS NULL
              AND items.expires_at IS NOT NULL
              AND items.expires_at <= date('now', ? || ' days')
              AND items.expires_at >= date('now', '-1 days')
            ORDER BY items.expires_at ASC
            """,
            (f"+{int(days)}",),
        ).fetchall()
        return [dict(r) for r in rows]


# ---- Loan tracking -----------------------------------------------------------
def set_loan(
    item_id: int,
    loaned_to_id: Optional[int],
    loaned_to_name: Optional[str],
    notes: Optional[str] = None,
    actor_name: Optional[str] = None,
) -> None:
    """Loan an item out, or pass all-NULL to clear the loan (returned)."""
    clearing = not (loaned_to_id or (loaned_to_name and loaned_to_name.strip()))
    with _cursor() as conn:
        if clearing:
            conn.execute(
                """
                UPDATE items
                   SET loaned_to_id = NULL,
                       loaned_to_name = NULL,
                       loaned_at = NULL,
                       loan_notes = NULL
                 WHERE id = ?
                """,
                (int(item_id),),
            )
        else:
            conn.execute(
                """
                UPDATE items
                   SET loaned_to_id = ?,
                       loaned_to_name = ?,
                       loaned_at = datetime('now'),
                       loan_notes = ?
                 WHERE id = ?
                """,
                (
                    int(loaned_to_id) if loaned_to_id else None,
                    (loaned_to_name or "").strip() or None,
                    (notes or "").strip() or None,
                    int(item_id),
                ),
            )
    if clearing:
        log_item_event(item_id, "return", detail=None, actor_name=actor_name)
    else:
        log_item_event(
            item_id, "loan",
            detail=(loaned_to_name or "").strip() or "(borrower)",
            actor_name=actor_name,
        )


def list_loaned_items() -> list[dict]:
    """All currently-loaned items."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT items.id, items.name, items.category, items.quantity,
                   items.boxes, items.estimated_value,
                   items.loaned_to_id, items.loaned_to_name,
                   items.loaned_at, items.loan_notes,
                   items.photo_id,
                   photos.path AS photo_path,
                   photos.taken_at AS photo_taken_at,
                   photos.room AS room
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE items.deleted_at IS NULL
              AND (items.loaned_to_id IS NOT NULL
                   OR items.loaned_to_name IS NOT NULL)
            ORDER BY items.loaned_at DESC
            """
        ).fetchall()
        return [_row_to_item(r) for r in rows]


def delete_item(item_id: int, actor_name: Optional[str] = None) -> None:
    """Soft-delete: stamp `deleted_at`. Item disappears from Search/Browse
    but can be restored from the Trash page."""
    with _cursor() as conn:
        conn.execute(
            "UPDATE items SET deleted_at = datetime('now') WHERE id = ?",
            (int(item_id),),
        )
    log_item_event(item_id, "deleted", detail=None, actor_name=actor_name)


def restore_item(item_id: int) -> None:
    """Undo a soft-delete."""
    with _cursor() as conn:
        conn.execute(
            "UPDATE items SET deleted_at = NULL WHERE id = ?",
            (int(item_id),),
        )


def purge_item(item_id: int) -> None:
    """Permanently delete an item. Not undoable."""
    with _cursor() as conn:
        conn.execute("DELETE FROM items WHERE id = ?", (int(item_id),))


def purge_all_deleted() -> int:
    """Permanently delete every soft-deleted item. Returns count purged."""
    with _cursor() as conn:
        cur = conn.execute(
            "DELETE FROM items WHERE deleted_at IS NOT NULL"
        )
        return int(cur.rowcount or 0)


def deleted_item_count() -> int:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM items WHERE deleted_at IS NOT NULL"
        ).fetchone()
        return int(row["n"]) if row else 0


# ---- Stats (for the home-page dashboard) -------------------------------------
def inventory_stats() -> dict:
    """Aggregate stats over active (non-deleted) items."""
    with _cursor() as conn:
        totals = conn.execute(
            """
            SELECT
              COUNT(*) AS total_items,
              COALESCE(SUM(estimated_value), 0) AS total_value,
              SUM(CASE WHEN for_sale = 1 THEN 1 ELSE 0 END) AS for_sale_count,
              COALESCE(
                SUM(CASE WHEN for_sale = 1 THEN estimated_value ELSE 0 END),
                0
              ) AS for_sale_value
            FROM items
            WHERE deleted_at IS NULL
            """
        ).fetchone()

        by_category = conn.execute(
            """
            SELECT category AS name,
                   COUNT(id) AS count,
                   COALESCE(SUM(estimated_value), 0) AS value
            FROM items
            WHERE deleted_at IS NULL
            GROUP BY category
            ORDER BY count DESC
            """
        ).fetchall()

        by_room = conn.execute(
            """
            SELECT photos.room AS name,
                   COUNT(items.id) AS count,
                   COALESCE(SUM(items.estimated_value), 0) AS value
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE items.deleted_at IS NULL
            GROUP BY photos.room
            ORDER BY count DESC
            """
        ).fetchall()

    return {
        "total_items": int(totals["total_items"] or 0),
        "total_value": float(totals["total_value"] or 0),
        "for_sale_count": int(totals["for_sale_count"] or 0),
        "for_sale_value": float(totals["for_sale_value"] or 0),
        "by_category": [
            {
                "name": r["name"] or "uncategorized",
                "count": int(r["count"]),
                "value": float(r["value"] or 0),
            }
            for r in by_category
        ],
        "by_room": [
            {
                "name": r["name"],
                "count": int(r["count"]),
                "value": float(r["value"] or 0),
            }
            for r in by_room
        ],
    }


def photo_path_by_id(photo_id: int) -> str:
    """Return the on-disk path stored for a photo row, or '' if missing.
    Used by the capture page's ?recent= rehydration to set photo_url
    when surfacing items saved via the REST upload endpoint."""
    with _cursor() as conn:
        row = conn.execute(
            "SELECT path FROM photos WHERE id = ?", (int(photo_id),)
        ).fetchone()
    return row["path"] if row else ""


def items_for_photo(photo_id: int) -> list[dict]:
    """Active (non-deleted) item rows tied to one photo. Used by the
    capture page's on_load after a direct-POST upload to repopulate the
    summary list."""
    with _cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM items WHERE photo_id = ? AND deleted_at IS NULL "
            "ORDER BY id ASC",
            (photo_id,),
        ).fetchall()
    return [_row_to_item(r) for r in rows]


def get_item_with_photo(item_id: int) -> Optional[dict]:
    """Look up an item joined with its photo path. Used by the crop server."""
    with _cursor() as conn:
        row = conn.execute(
            """
            SELECT items.id, items.name, items.boxes, photos.path AS photo_path
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE items.id = ?
            """,
            (int(item_id),),
        ).fetchone()
        return _row_to_item(row) if row else None


def get_item(item_id: int) -> Optional[dict]:
    """Full item lookup including all editable fields."""
    with _cursor() as conn:
        row = conn.execute(
            """
            SELECT items.id, items.name, items.category, items.quantity,
                   items.detector_count, items.boxes,
                   items.for_sale, items.estimated_value, items.created_at,
                   items.photo_id, items.expires_at,
                   items.purchase_date, items.purchase_price,
                   items.purchase_store, items.return_until,
                   items.warranty_until,
                   photos.path AS photo_path, photos.room
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE items.id = ?
            """,
            (int(item_id),),
        ).fetchone()
        return _row_to_item(row) if row else None


FOOD_CATEGORIES: tuple[str, ...] = (
    "pantry / food",
    "spice / seasoning",
)


def food_items() -> list[dict]:
    """All active items whose category is food-related (pantry, spices)."""
    placeholders = ",".join("?" for _ in FOOD_CATEGORIES)
    with _cursor() as conn:
        rows = conn.execute(
            f"""
            SELECT items.id, items.name, items.category, items.quantity,
                   items.detector_count, items.boxes,
                   items.for_sale, items.estimated_value, items.created_at,
                   items.photo_id,
                   photos.path AS photo_path,
                   photos.taken_at AS photo_taken_at,
                   photos.room AS room
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE items.category IN ({placeholders})
              AND items.deleted_at IS NULL
            ORDER BY items.created_at DESC
            """,
            FOOD_CATEGORIES,
        ).fetchall()
        return [_row_to_item(r) for r in rows]


def for_sale_items() -> list[dict]:
    """All active items currently marked for sale."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT items.id, items.name, items.category, items.quantity,
                   items.detector_count, items.boxes,
                   items.for_sale, items.estimated_value, items.created_at,
                   items.photo_id,
                   photos.path AS photo_path,
                   photos.taken_at AS photo_taken_at,
                   photos.room AS room
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE items.for_sale = 1 AND items.deleted_at IS NULL
            ORDER BY items.created_at DESC
            """
        ).fetchall()
        return [_row_to_item(r) for r in rows]


def has_item(name_query: str) -> bool:
    """True if any active inventory item's name matches `name_query`
    (case-insensitive substring). Used by Meals to decide whether a missing
    ingredient should be added to the grocery list."""
    if not (name_query or "").strip():
        return False
    pattern = f"%{name_query.lower().strip()}%"
    with _cursor() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM items
            WHERE LOWER(name) LIKE ? AND deleted_at IS NULL
            LIMIT 1
            """,
            (pattern,),
        ).fetchone()
    return row is not None


def update_item(
    item_id: int,
    name: str,
    quantity: int,
    category: str,
    for_sale: Optional[bool] = None,
    estimated_value=None,
    actor_name: Optional[str] = None,
) -> None:
    """Update the editable fields on an item row.

    `boxes`, `detector_count`, `photo_id`, `created_at` are not editable —
    they're tied to the original recognition pass.

    Pass `for_sale=None` or `estimated_value=None` to leave those untouched
    (None for estimated_value is otherwise a valid value meaning 'unknown',
    so we use a sentinel — pass an explicit value to clear).
    """
    sets = ["name = ?", "quantity = ?", "category = ?"]
    args: list = [name, int(quantity), category]
    if for_sale is not None:
        sets.append("for_sale = ?")
        args.append(1 if for_sale else 0)
    if estimated_value is not None:
        sets.append("estimated_value = ?")
        args.append(_coerce_value(estimated_value))
    args.append(int(item_id))
    # Snapshot old quantity so we can emit a precise history event.
    old_q: Optional[int] = None
    try:
        with _cursor() as conn:
            row = conn.execute(
                "SELECT quantity FROM items WHERE id = ?", (int(item_id),)
            ).fetchone()
            if row:
                old_q = int(row["quantity"])
    except Exception:
        old_q = None
    with _cursor() as conn:
        conn.execute(
            f"UPDATE items SET {', '.join(sets)} WHERE id = ?", args
        )
    if old_q is not None and int(quantity) != old_q:
        log_item_event(
            item_id, "quantity",
            detail={"from": old_q, "to": int(quantity)},
            actor_name=actor_name,
        )


# ---- Purchase / warranty / return-window ------------------------------------
def set_purchase(
    item_id: int,
    purchase_date: Optional[str] = None,
    price: Optional[float] = None,
    store: Optional[str] = None,
    return_until: Optional[str] = None,
    actor_name: Optional[str] = None,
) -> None:
    """Record purchase metadata on an item. Any None/blank value is left
    untouched on the row (use empty string '' to explicitly clear).

    Emits a `price` history event when the price is being set.
    """
    sets: list[str] = []
    args: list = []
    if purchase_date is not None:
        sets.append("purchase_date = ?")
        args.append((purchase_date or "").strip() or None)
    if price is not None:
        sets.append("purchase_price = ?")
        args.append(_coerce_value(price))
    if store is not None:
        sets.append("purchase_store = ?")
        args.append((store or "").strip() or None)
    if return_until is not None:
        sets.append("return_until = ?")
        args.append((return_until or "").strip() or None)
    if not sets:
        return
    args.append(int(item_id))
    with _cursor() as conn:
        conn.execute(
            f"UPDATE items SET {', '.join(sets)} WHERE id = ?", args
        )
    if price is not None:
        log_item_event(
            item_id, "price",
            detail={
                "price": _coerce_value(price),
                "store": (store or "").strip() or None,
                "date": (purchase_date or "").strip() or None,
            },
            actor_name=actor_name,
        )


def set_warranty(
    item_id: int,
    return_until: Optional[str] = None,
    warranty_until: Optional[str] = None,
    actor_name: Optional[str] = None,
) -> None:
    """Set return-window cutoff and/or warranty expiration. Pass empty
    string to clear; None leaves the column untouched."""
    sets: list[str] = []
    args: list = []
    if return_until is not None:
        sets.append("return_until = ?")
        args.append((return_until or "").strip() or None)
    if warranty_until is not None:
        sets.append("warranty_until = ?")
        args.append((warranty_until or "").strip() or None)
    if not sets:
        return
    args.append(int(item_id))
    with _cursor() as conn:
        conn.execute(
            f"UPDATE items SET {', '.join(sets)} WHERE id = ?", args
        )
    log_item_event(
        item_id, "warranty",
        detail={
            "return_until": (return_until or "").strip() or None,
            "warranty_until": (warranty_until or "").strip() or None,
        },
        actor_name=actor_name,
    )


def items_returnable_within(days: int = 14) -> list[dict]:
    """Active items whose return-window cutoff falls in [today, today+N]."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT items.id, items.name, items.return_until,
                   items.purchase_store, photos.room AS room
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE items.deleted_at IS NULL
              AND items.return_until IS NOT NULL
              AND items.return_until <= date('now', ? || ' days')
              AND items.return_until >= date('now', '-1 days')
            ORDER BY items.return_until ASC
            """,
            (f"+{int(days)}",),
        ).fetchall()
        return [dict(r) for r in rows]


def items_warranty_expiring_within(days: int = 30) -> list[dict]:
    """Active items whose warranty expiry falls in [today, today+N]."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT items.id, items.name, items.warranty_until,
                   items.purchase_store, photos.room AS room
            FROM items
            JOIN photos ON items.photo_id = photos.id
            WHERE items.deleted_at IS NULL
              AND items.warranty_until IS NOT NULL
              AND items.warranty_until <= date('now', ? || ' days')
              AND items.warranty_until >= date('now', '-1 days')
            ORDER BY items.warranty_until ASC
            """,
            (f"+{int(days)}",),
        ).fetchall()
        return [dict(r) for r in rows]


def update_photo_room(photo_id: int, room: str) -> None:
    """Move a photo (and all its items) to a different room."""
    with _cursor() as conn:
        conn.execute(
            "UPDATE photos SET room = ? WHERE id = ?",
            (room, int(photo_id)),
        )


def recent_item_events(limit: int = 20) -> list[dict]:
    """Recent item-history events across ALL items, joined with item name
    so the home-page activity feed can render one-liners. Newest first."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT h.id, h.item_id, h.ts, h.actor_name, h.kind, h.detail,
                   items.name AS item_name
              FROM item_history h
              LEFT JOIN items ON items.id = h.item_id
             WHERE items.deleted_at IS NULL
             ORDER BY h.ts DESC, h.id DESC
             LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]

