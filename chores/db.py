"""SQLite layer for the Chores tool.

Two tables:
  - people: household members who can be assigned tasks
  - tasks: one row per task; one assignee at most; completed flag

Tasks are not sightings (unlike inventory items) — they're discrete
to-do items with a lifecycle (created → optionally assigned → completed).
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

import config


# ---- Password hashing --------------------------------------------------------
# pbkdf2-sha256, dependency-free. OWASP (2023+) recommends 600k iterations.
# Stored hashes encode their own iteration count so old hashes still verify.
_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        scheme, iter_str, salt_hex, hash_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iter_str)
        )
        return secrets.compare_digest(actual, expected)
    except (ValueError, AttributeError):
        return False


def password_hash_needs_upgrade(stored: Optional[str]) -> bool:
    """True if the stored hash was computed with fewer iterations than the
    current target. Callers should re-hash with `hash_password` on next
    successful login."""
    if not stored:
        return False
    try:
        _, iter_str, _, _ = stored.split("$")
        return int(iter_str) < _PBKDF2_ITERATIONS
    except (ValueError, AttributeError):
        return False


def update_password_hash(user_id: int, password: str) -> None:
    """Rehash and store a new password hash for the given user. Used to
    transparently upgrade legacy weak hashes on successful login."""
    with _cursor() as conn:
        conn.execute(
            "UPDATE people SET password_hash = ? WHERE id = ?",
            (hash_password(password), int(user_id)),
        )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.CHORES_DB_PATH)
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
    """Create tables if missing. Runs in-place migrations for added columns.
    Idempotent.
    """
    config.CHORES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _cursor() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS people (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              color TEXT NOT NULL DEFAULT '#888888',
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tasks (
              id INTEGER PRIMARY KEY,
              title TEXT NOT NULL,
              description TEXT,
              assigned_to INTEGER REFERENCES people(id) ON DELETE SET NULL,
              due_date TEXT,
              completed INTEGER NOT NULL DEFAULT 0,
              completed_at TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to);
            CREATE INDEX IF NOT EXISTS idx_tasks_completed ON tasks(completed);
            """
        )

        # Migrations: extend `people` to become the unified User table.
        existing = {r[1] for r in conn.execute("PRAGMA table_info(people)")}
        if "email" not in existing:
            conn.execute("ALTER TABLE people ADD COLUMN email TEXT")
        if "avatar_url" not in existing:
            conn.execute("ALTER TABLE people ADD COLUMN avatar_url TEXT")
        if "auth_subject" not in existing:
            # Reserved for SSO integrations; unused with local-only auth.
            conn.execute("ALTER TABLE people ADD COLUMN auth_subject TEXT")
        if "is_admin" not in existing:
            conn.execute(
                "ALTER TABLE people ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
            )
        if "username" not in existing:
            conn.execute("ALTER TABLE people ADD COLUMN username TEXT")
        if "password_hash" not in existing:
            conn.execute("ALTER TABLE people ADD COLUMN password_hash TEXT")
        # Per-module RBAC flags. Default new fields to 1 (allowed) so existing
        # rows remain functional.
        for col in (
            "can_read_inventory",
            "can_write_inventory",
            "can_read_chores",
            "can_write_chores",
        ):
            if col not in existing:
                conn.execute(
                    f"ALTER TABLE people ADD COLUMN {col} INTEGER NOT NULL DEFAULT 1"
                )

        # Unique index on username — SQLite UNIQUE allows multiple NULLs.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_people_username ON people(username)"
        )

        # Per-user iCal subscription token. Random opaque string used in
        # /calendar.ics URLs so phone calendar apps (which don't speak
        # cookies) can authenticate. Rotates on demand via Settings.
        if "ical_token" not in existing:
            conn.execute("ALTER TABLE people ADD COLUMN ical_token TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_people_ical "
            "ON people(ical_token)"
        )

        # Migration: completion_photo_path on tasks for proof-of-completion.
        task_cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        if "completion_photo_path" not in task_cols:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN completion_photo_path TEXT"
            )
        # Recurrence: a compact code like 'daily', 'weekly:MON,WED',
        # 'monthly:1' (day of month), 'yearly'. NULL = one-shot. When a
        # recurring task is completed, the reminder dispatcher materializes
        # the next instance and the original is marked done. `parent_id`
        # links instances back to their parent so we can compute streaks
        # / disable a series.
        if "recurrence" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN recurrence TEXT")
        if "parent_task_id" not in task_cols:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN parent_task_id INTEGER"
            )

        # Sessions table for remember-me cookies. Tokens are stored as SHA-256
        # hashes so a DB read doesn't reveal live session tokens.
        # Plus audit_log for admin / security event history.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
              expires_at TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY,
              actor_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
              actor_name TEXT,
              action TEXT NOT NULL,
              target TEXT,
              detail TEXT,
              ip TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        # In-place migration for the ip column on older audit_log tables.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_log)")}
        if "ip" not in cols:
            conn.execute("ALTER TABLE audit_log ADD COLUMN ip TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_created "
            "ON audit_log(created_at DESC)"
        )


# ---- People / Users ----------------------------------------------------------
# `people` is the unified user table. Existing rows just have name+color;
# email/avatar/auth/admin fields fill in once auth is wired up (Iteration 2/3).
_USER_COLUMNS = (
    "id, name, color, email, avatar_url, is_admin, auth_subject, "
    "username, password_hash, "
    "can_read_inventory, can_write_inventory, "
    "can_read_chores, can_write_chores, ical_token, created_at"
)


def ensure_ical_token(user_id: int) -> str:
    """Return this user's iCal subscription token, minting one on first call."""
    with _cursor() as conn:
        row = conn.execute(
            "SELECT ical_token FROM people WHERE id = ?", (int(user_id),),
        ).fetchone()
        if row and row[0]:
            return row[0]
        tok = secrets.token_urlsafe(24)
        conn.execute(
            "UPDATE people SET ical_token = ? WHERE id = ?",
            (tok, int(user_id)),
        )
        return tok


def rotate_ical_token(user_id: int) -> str:
    """Force-mint a new iCal token — invalidates any existing subscriptions."""
    tok = secrets.token_urlsafe(24)
    with _cursor() as conn:
        conn.execute(
            "UPDATE people SET ical_token = ? WHERE id = ?",
            (tok, int(user_id)),
        )
    return tok


def user_by_ical_token(token: str) -> Optional[dict]:
    if not token:
        return None
    with _cursor() as conn:
        row = conn.execute(
            f"SELECT {_USER_COLUMNS} FROM people WHERE ical_token = ?",
            (token,),
        ).fetchone()
        return dict(row) if row else None


def list_people() -> list[dict]:
    with _cursor() as conn:
        rows = conn.execute(
            f"SELECT {_USER_COLUMNS} FROM people ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]


def _canonical_username(s: str) -> str:
    """Normalize a username: strip whitespace and lowercase. The single
    canonical form is what we store and compare against, so 'Justin',
    'JUSTIN', and ' justin ' all resolve to the same account."""
    return (s or "").strip().lower()


def get_user_by_username(username: str) -> Optional[dict]:
    canon = _canonical_username(username)
    if not canon:
        return None
    with _cursor() as conn:
        row = conn.execute(
            f"SELECT {_USER_COLUMNS} FROM people WHERE LOWER(username) = ?",
            (canon,),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with _cursor() as conn:
        row = conn.execute(
            f"SELECT {_USER_COLUMNS} FROM people WHERE id = ?",
            (int(user_id),),
        ).fetchone()
        return dict(row) if row else None


def has_any_authed_users() -> bool:
    """True if at least one user has username + password set. Used to detect
    the first-run state."""
    with _cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM people "
            "WHERE username IS NOT NULL AND password_hash IS NOT NULL"
        ).fetchone()
        return int(row["n"]) > 0


def set_user_credentials(
    user_id: int,
    username: str,
    password: Optional[str] = None,
) -> None:
    """Set username (always lowercased) and optionally rotate password.

    Pass `password=None` to leave the existing password hash alone — useful
    when an admin just wants to fix a username typo without forcing a reset.
    """
    canon = _canonical_username(username)
    if not canon:
        raise ValueError("Username can't be empty")
    with _cursor() as conn:
        # Reject if the canonical username is taken by a different user.
        clash = conn.execute(
            "SELECT id FROM people WHERE LOWER(username) = ? AND id != ?",
            (canon, int(user_id)),
        ).fetchone()
        if clash:
            raise ValueError(f"Username '{canon}' is already taken")
        if password:
            conn.execute(
                "UPDATE people SET username = ?, password_hash = ? "
                "WHERE id = ?",
                (canon, hash_password(password), int(user_id)),
            )
        else:
            conn.execute(
                "UPDATE people SET username = ? WHERE id = ?",
                (canon, int(user_id)),
            )


def set_permissions(
    user_id: int,
    *,
    is_admin: Optional[bool] = None,
    can_read_inventory: Optional[bool] = None,
    can_write_inventory: Optional[bool] = None,
    can_read_chores: Optional[bool] = None,
    can_write_chores: Optional[bool] = None,
) -> None:
    """Update any subset of permission flags."""
    fields: list[str] = []
    values: list = []
    for col, val in [
        ("is_admin", is_admin),
        ("can_read_inventory", can_read_inventory),
        ("can_write_inventory", can_write_inventory),
        ("can_read_chores", can_read_chores),
        ("can_write_chores", can_write_chores),
    ]:
        if val is not None:
            fields.append(f"{col} = ?")
            values.append(1 if val else 0)
    if not fields:
        return
    values.append(int(user_id))
    with _cursor() as conn:
        conn.execute(
            f"UPDATE people SET {', '.join(fields)} WHERE id = ?", values
        )


def derive_color(seed: str | int) -> str:
    """Deterministically pick a chore-chip color for a user. We keep the
    color column in the DB (legacy chore-assignment chips reference it),
    but it's no longer user-editable — derived from the user id so each
    user always renders with the same accent."""
    palette = config.PERSON_COLORS or ["#888888"]
    s = str(seed)
    digest = int(hashlib.sha256(s.encode("utf-8")).hexdigest(), 16)
    return palette[digest % len(palette)]


def create_first_admin(
    name: str,
    username: str,
    password: str,
) -> int:
    """Create the first admin user. All permissions on, marks as admin.
    Username is stored lowercased; color is auto-derived from the new row id."""
    canon = _canonical_username(username)
    if not canon:
        raise ValueError("Username can't be empty")
    with _cursor() as conn:
        cur = conn.execute(
            """
            INSERT INTO people
                (name, color, username, password_hash, is_admin,
                 can_read_inventory, can_write_inventory,
                 can_read_chores, can_write_chores)
            VALUES (?, ?, ?, ?, 1, 1, 1, 1, 1)
            """,
            (
                name.strip(),
                "#888888",   # placeholder, replaced just below
                canon,
                hash_password(password),
            ),
        )
        new_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE people SET color = ? WHERE id = ?",
            (derive_color(new_id), new_id),
        )
        return new_id


def add_person(
    name: str,
    email: str | None = None,
    is_admin: bool = False,
) -> int:
    """Create a household member. Color is auto-derived from the id; not a
    user-editable attribute anymore."""
    with _cursor() as conn:
        cur = conn.execute(
            """
            INSERT INTO people (name, color, email, is_admin)
            VALUES (?, ?, ?, ?)
            """,
            (name.strip(), "#888888", email, 1 if is_admin else 0),
        )
        new_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE people SET color = ? WHERE id = ?",
            (derive_color(new_id), new_id),
        )
        return new_id


def update_person(
    person_id: int,
    *,
    name: Optional[str] = None,
    email: Optional[str] = None,
    is_admin: Optional[bool] = None,
) -> None:
    """Update any subset of the person's profile fields. Pass None for any
    field to leave it unchanged."""
    sets: list[str] = []
    args: list = []
    if name is not None:
        sets.append("name = ?")
        args.append(name.strip())
    if email is not None:
        sets.append("email = ?")
        args.append((email or "").strip() or None)
    if is_admin is not None:
        sets.append("is_admin = ?")
        args.append(1 if is_admin else 0)
    if not sets:
        return
    args.append(int(person_id))
    with _cursor() as conn:
        conn.execute(
            f"UPDATE people SET {', '.join(sets)} WHERE id = ?",
            args,
        )


def delete_person(person_id: int) -> None:
    """Delete a person. Tasks assigned to them become unassigned (FK ON DELETE
    SET NULL handles this)."""
    with _cursor() as conn:
        conn.execute("DELETE FROM people WHERE id = ?", (int(person_id),))


def person_task_count(person_id: int) -> int:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE assigned_to = ?",
            (int(person_id),),
        ).fetchone()
        return int(row["n"]) if row else 0


# ---- Tasks -------------------------------------------------------------------
def list_tasks(
    assigned_to: Optional[int] = None,
    include_completed: bool = False,
    only_completed: bool = False,
) -> list[dict]:
    """List tasks, joined with the assignee's name and color.

    - `assigned_to=None`: don't filter by assignee.
    - `assigned_to=0`: only unassigned tasks.
    - `assigned_to=<id>`: only that person's tasks.
    """
    sql = [
        """
        SELECT tasks.id, tasks.title, tasks.description, tasks.assigned_to,
               tasks.due_date, tasks.completed, tasks.completed_at,
               tasks.created_at, tasks.completion_photo_path,
               tasks.recurrence, tasks.parent_task_id,
               people.name AS assignee_name, people.color AS assignee_color
        FROM tasks
        LEFT JOIN people ON tasks.assigned_to = people.id
        """
    ]
    conditions: list[str] = []
    params: list = []

    if assigned_to is None:
        pass
    elif assigned_to == 0:
        conditions.append("tasks.assigned_to IS NULL")
    else:
        conditions.append("tasks.assigned_to = ?")
        params.append(int(assigned_to))

    if only_completed:
        conditions.append("tasks.completed = 1")
    elif not include_completed:
        conditions.append("tasks.completed = 0")

    if conditions:
        sql.append("WHERE " + " AND ".join(conditions))

    sql.append(
        """
        ORDER BY tasks.completed ASC,
                 CASE WHEN tasks.due_date IS NULL THEN 1 ELSE 0 END,
                 tasks.due_date ASC,
                 tasks.created_at DESC
        """
    )
    with _cursor() as conn:
        rows = conn.execute("\n".join(sql), params).fetchall()
        return [dict(r) for r in rows]


def add_task(
    title: str,
    description: Optional[str] = None,
    assigned_to: Optional[int] = None,
    due_date: Optional[str] = None,
    recurrence: Optional[str] = None,
    parent_task_id: Optional[int] = None,
) -> int:
    with _cursor() as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks
                (title, description, assigned_to, due_date,
                 recurrence, parent_task_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                description.strip() if description else None,
                int(assigned_to) if assigned_to else None,
                due_date,
                (recurrence or "").strip() or None,
                int(parent_task_id) if parent_task_id else None,
            ),
        )
        return int(cur.lastrowid)


def update_task(
    task_id: int,
    title: str,
    description: Optional[str],
    assigned_to: Optional[int],
    due_date: Optional[str],
    recurrence: Optional[str] = None,
) -> None:
    with _cursor() as conn:
        conn.execute(
            """
            UPDATE tasks
               SET title = ?, description = ?, assigned_to = ?, due_date = ?,
                   recurrence = ?
             WHERE id = ?
            """,
            (
                title.strip(),
                description.strip() if description else None,
                int(assigned_to) if assigned_to else None,
                due_date,
                (recurrence or "").strip() or None,
                int(task_id),
            ),
        )


def get_task(task_id: int) -> Optional[dict]:
    with _cursor() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (int(task_id),),
        ).fetchone()
        return dict(row) if row else None


def mark_complete(task_id: int, completed: bool = True) -> None:
    with _cursor() as conn:
        if completed:
            conn.execute(
                """
                UPDATE tasks
                   SET completed = 1, completed_at = datetime('now')
                 WHERE id = ?
                """,
                (int(task_id),),
            )
        else:
            conn.execute(
                """
                UPDATE tasks
                   SET completed = 0, completed_at = NULL
                 WHERE id = ?
                """,
                (int(task_id),),
            )


# ---- Recurrence --------------------------------------------------------------
def _next_due_date(rule: str, after: str) -> Optional[str]:
    """Given a recurrence rule and a 'YYYY-MM-DD' anchor, return the next
    occurrence date as 'YYYY-MM-DD', or None if the rule is unknown/empty.

    Supported rules (case-insensitive):
      - daily
      - weekly                 -> same weekday next week
      - weekly:MON,WED,FRI     -> next listed weekday after `after`
      - monthly                -> same day of next month (or month-end)
      - monthly:15             -> 15th of next month (or month-end if shorter)
      - yearly                 -> same month-day next year
    """
    from datetime import date as _date, timedelta as _td
    import calendar as _cal

    if not rule:
        return None
    try:
        anchor = _date.fromisoformat(after)
    except (ValueError, TypeError):
        anchor = _date.today()

    rule = rule.strip().lower()
    head, _, tail = rule.partition(":")
    head = head.strip()
    tail = tail.strip()

    weekday_map = {
        "mon": 0, "tue": 1, "wed": 2, "thu": 3,
        "fri": 4, "sat": 5, "sun": 6,
    }

    if head == "daily":
        return (anchor + _td(days=1)).isoformat()

    if head == "weekly":
        if not tail:
            return (anchor + _td(days=7)).isoformat()
        targets = sorted(
            weekday_map[w.strip()[:3]] for w in tail.split(",")
            if w.strip()[:3] in weekday_map
        )
        if not targets:
            return (anchor + _td(days=7)).isoformat()
        for step in range(1, 15):
            d = anchor + _td(days=step)
            if d.weekday() in targets:
                return d.isoformat()
        return (anchor + _td(days=7)).isoformat()

    if head == "monthly":
        y, m = anchor.year, anchor.month
        # Day-of-month: explicit if given, otherwise reuse anchor.day.
        try:
            target_day = int(tail) if tail else anchor.day
        except ValueError:
            target_day = anchor.day
        # Advance one month.
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
        last_day = _cal.monthrange(y, m)[1]
        d = _date(y, m, min(target_day, last_day))
        return d.isoformat()

    if head == "yearly":
        try:
            return _date(anchor.year + 1, anchor.month, anchor.day).isoformat()
        except ValueError:
            # Feb 29 -> Feb 28.
            return _date(anchor.year + 1, anchor.month, 28).isoformat()

    return None


def mark_complete_and_advance(task_id: int) -> Optional[int]:
    """Mark a task done. If it carries a recurrence rule, also create the
    next instance and return its new id. The original keeps its history."""
    task = get_task(int(task_id))
    if not task:
        return None
    mark_complete(int(task_id), True)
    rule = (task.get("recurrence") or "").strip()
    if not rule:
        return None
    base = task.get("due_date") or _today_iso()
    next_due = _next_due_date(rule, base)
    if not next_due:
        return None
    return add_task(
        title=task["title"],
        description=task.get("description"),
        assigned_to=task.get("assigned_to"),
        due_date=next_due,
        recurrence=rule,
        parent_task_id=task.get("parent_task_id") or task["id"],
    )


def _today_iso() -> str:
    from datetime import date as _date
    return _date.today().isoformat()


def delete_task(task_id: int) -> None:
    with _cursor() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))


def set_task_photo(task_id: int, photo_path: Optional[str]) -> None:
    """Attach (or clear) a proof-of-completion photo path on a task."""
    with _cursor() as conn:
        conn.execute(
            "UPDATE tasks SET completion_photo_path = ? WHERE id = ?",
            (photo_path, int(task_id)),
        )


# ---- Sessions ----------------------------------------------------------------
def _hash_token(token: str) -> str:
    """SHA-256 of a random 256-bit token. Random tokens don't need pbkdf2."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int, days: int = 30) -> str:
    """Create a new session for `user_id`. Returns the raw token (only here).

    The DB only ever stores the hash — so a DB read can't impersonate users.
    """
    from datetime import datetime, timedelta

    token = secrets.token_urlsafe(32)  # ~256 bits of entropy
    token_hash = _hash_token(token)
    expires_at = (
        datetime.now() + timedelta(days=int(days))
    ).strftime("%Y-%m-%d %H:%M:%S")
    with _cursor() as conn:
        conn.execute(
            """
            INSERT INTO sessions (token_hash, user_id, expires_at)
            VALUES (?, ?, ?)
            """,
            (token_hash, int(user_id), expires_at),
        )
    return token


def validate_session(token: Optional[str]) -> Optional[dict]:
    """If `token` matches an active (non-expired) session, return the user."""
    if not token:
        return None
    token_hash = _hash_token(token)
    with _cursor() as conn:
        row = conn.execute(
            """
            SELECT user_id FROM sessions
            WHERE token_hash = ? AND expires_at > datetime('now')
            """,
            (token_hash,),
        ).fetchone()
    if not row:
        return None
    return get_user_by_id(int(row["user_id"]))


def delete_sessions_for_user(user_id: int) -> int:
    """Revoke every session belonging to a single user. Used by 'log out
    everywhere' and admin account-revocation flows. Returns the number of
    sessions invalidated."""
    with _cursor() as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE user_id = ?", (int(user_id),),
        )
        return int(cur.rowcount or 0)


def delete_session(token: Optional[str]) -> None:
    if not token:
        return
    token_hash = _hash_token(token)
    with _cursor() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def purge_expired_sessions() -> int:
    with _cursor() as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE expires_at <= datetime('now')"
        )
        return int(cur.rowcount or 0)


# ---- Audit log ---------------------------------------------------------------
def log_audit(
    actor_id: Optional[int],
    actor_name: Optional[str],
    action: str,
    target: Optional[str] = None,
    detail: Optional[str] = None,
    ip: Optional[str] = None,
) -> None:
    """Record a single admin/security-relevant action. Best-effort: never
    raises into the caller — failure to log shouldn't block the action."""
    import sys as _sys
    try:
        with _cursor() as conn:
            conn.execute(
                """
                INSERT INTO audit_log
                    (actor_id, actor_name, action, target, detail, ip)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(actor_id) if actor_id else None,
                    (actor_name or "")[:120] or None,
                    action[:60],
                    (target or "")[:200] or None,
                    (detail or "")[:500] or None,
                    (ip or "")[:45] or None,
                ),
            )
    except Exception as exc:
        # Surface failures to the journal so we don't silently lose audit
        # rows. Still don't raise — audit MUST not block the action.
        print(f"[audit] log failed: {type(exc).__name__}: {exc}",
              file=_sys.stderr, flush=True)


def list_audit(limit: int = 200) -> list[dict]:
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT id, actor_id, actor_name, action, target, detail,
                   ip, created_at
            FROM audit_log
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def chores_stats() -> dict:
    """Aggregate stats for the home-page dashboard."""
    with _cursor() as conn:
        totals = conn.execute(
            """
            SELECT
              SUM(CASE WHEN completed = 0 THEN 1 ELSE 0 END) AS open_count,
              SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) AS done_count,
              SUM(
                CASE
                  WHEN completed = 0
                   AND due_date IS NOT NULL
                   AND due_date < date('now')
                  THEN 1 ELSE 0
                END
              ) AS overdue_count
            FROM tasks
            """
        ).fetchone()

        per_person = conn.execute(
            """
            SELECT
              COALESCE(people.name, 'Unassigned') AS name,
              COALESCE(people.color, '#888888')   AS color,
              SUM(CASE WHEN tasks.completed = 0 THEN 1 ELSE 0 END) AS open_count,
              SUM(CASE WHEN tasks.completed = 1 THEN 1 ELSE 0 END) AS done_count
            FROM tasks
            LEFT JOIN people ON tasks.assigned_to = people.id
            GROUP BY tasks.assigned_to
            ORDER BY open_count DESC, name ASC
            """
        ).fetchall()

    return {
        "open": int(totals["open_count"] or 0) if totals else 0,
        "done": int(totals["done_count"] or 0) if totals else 0,
        "overdue": int(totals["overdue_count"] or 0) if totals else 0,
        "per_person": [
            {
                "name": r["name"],
                "color": r["color"] or "#888888",
                "open": int(r["open_count"] or 0),
                "done": int(r["done_count"] or 0),
            }
            for r in per_person
        ],
    }


def task_summary_by_person() -> list[dict]:
    """Returns counts of open vs completed tasks per person, plus an
    'Unassigned' bucket."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT
              COALESCE(people.name, 'Unassigned') AS name,
              COALESCE(people.color, '#888888')   AS color,
              SUM(CASE WHEN tasks.completed = 0 THEN 1 ELSE 0 END) AS open_count,
              SUM(CASE WHEN tasks.completed = 1 THEN 1 ELSE 0 END) AS done_count
            FROM tasks
            LEFT JOIN people ON tasks.assigned_to = people.id
            GROUP BY tasks.assigned_to
            ORDER BY open_count DESC, name ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def recent_completions(limit: int = 20) -> list[dict]:
    """Most recently completed tasks for the home-page activity feed."""
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT tasks.id, tasks.title, tasks.completed_at,
                   tasks.assigned_to, people.name AS assignee_name
              FROM tasks
              LEFT JOIN people ON tasks.assigned_to = people.id
             WHERE tasks.completed = 1
               AND tasks.completed_at IS NOT NULL
             ORDER BY tasks.completed_at DESC, tasks.id DESC
             LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]

