"""GYST reminder dispatcher.

Run every ~15 minutes. Looks at the DB and fires web-push notifications:

  - Open tasks whose due_date is today and whose assignee has at least one
    push subscription. Each task is reminded once per day per user.
  - Appointments starting within the next hour. Each appointment is
    reminded at most once per (user, appointment) pair.

State is deduplicated via a `reminder_sent` table inside notifications.db
so a flaky cron run doesn't double-fire.

Designed to be invoked twice per run — once with --env dev, once with
--env prod — each pointing at its own data dir via PYTHONPATH.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _add_reminder_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminder_sent (
          kind TEXT NOT NULL,
          key TEXT NOT NULL,
          user_id INTEGER NOT NULL,
          sent_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (kind, key, user_id)
        )
        """
    )


def _was_sent(conn: sqlite3.Connection, kind: str, key: str, user_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM reminder_sent WHERE kind = ? AND key = ? AND user_id = ?",
        (kind, key, int(user_id)),
    ).fetchone()
    return row is not None


def _mark_sent(conn: sqlite3.Connection, kind: str, key: str, user_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO reminder_sent (kind, key, user_id) "
        "VALUES (?, ?, ?)",
        (kind, key, int(user_id)),
    )
    conn.commit()


def _purge_old_reminders(conn: sqlite3.Connection) -> None:
    # Anything older than 14 days is irrelevant — keeps the table tiny.
    conn.execute(
        "DELETE FROM reminder_sent WHERE sent_at < datetime('now', '-14 days')"
    )


def run() -> int:
    """Returns the number of pushes actually delivered."""
    import config
    from chores import db as chores_db
    from appointments import db as appt_db
    from notifications import db as push_db

    chores_db.init_db()
    appt_db.init_db()
    push_db.init_db()

    # Reminder dedupe table lives next to push subscriptions.
    conn = sqlite3.connect(config.NOTIFICATIONS_DB_PATH)
    _add_reminder_table(conn)
    _purge_old_reminders(conn)

    delivered = 0
    today = datetime.now().date().isoformat()

    # --- Chores due today ----------------------------------------------------
    for t in chores_db.list_tasks(include_completed=False):
        due = (t.get("due_date") or "").strip()
        if due != today:
            continue
        assignee = t.get("assigned_to")
        if not assignee:
            continue
        if push_db.count_subscriptions_for_user(int(assignee)) == 0:
            continue
        key = f"task:{t['id']}:{today}"
        if _was_sent(conn, "task_due", key, int(assignee)):
            continue
        title = "Task due today"
        body = t["title"]
        res = push_db.send_to_user(
            int(assignee), title=title, body=body, url="/chores/tasks",
        )
        if res["sent"] > 0:
            _mark_sent(conn, "task_due", key, int(assignee))
            delivered += res["sent"]

    # --- Advance any past-due recurring appointments ------------------------
    # Materialize the next instance before we look for appointments to remind.
    for a in appt_db.list_appointments(upcoming_only=False):
        if a.get("recurrence"):
            try:
                appt_db.advance_recurrence(int(a["id"]))
            except Exception as exc:
                import sys
                print(f"[reminders] advance failed for {a['id']}: {exc}",
                      file=sys.stderr)

    # --- Appointments in the next hour --------------------------------------
    now = datetime.now()
    soon = now + timedelta(minutes=60)
    for a in appt_db.list_appointments(upcoming_only=True):
        when = (a.get("appointment_at") or "").strip()
        try:
            dt = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if not (now <= dt <= soon):
            continue
        targets: list[int] = []
        for_id = a.get("for_person_id") or a.get("for_id")
        if for_id:
            targets = [int(for_id)]
        else:
            # "Anyone" — notify every user that has at least one subscription.
            targets = [
                int(p["id"]) for p in chores_db.list_people()
                if push_db.count_subscriptions_for_user(int(p["id"])) > 0
            ]
        key = f"appt:{a['id']}"
        title = "Upcoming appointment"
        body = f"{a['title']} at {dt.strftime('%H:%M')}"
        for uid in targets:
            if _was_sent(conn, "appt_soon", key, uid):
                continue
            res = push_db.send_to_user(
                uid, title=title, body=body, url="/appointments",
            )
            if res["sent"] > 0:
                _mark_sent(conn, "appt_soon", key, uid)
                delivered += res["sent"]

    # --- Items expiring within 3 days ----------------------------------------
    # One reminder per item per day, broadcast to every subscribed user
    # (any household member should be able to act on it).
    try:
        from inventory import db as inv_db
        inv_db.init_db()
        expiring = inv_db.items_expiring_within(3)
    except Exception:
        expiring = []
    if expiring:
        recipients = [
            int(p["id"]) for p in chores_db.list_people()
            if push_db.count_subscriptions_for_user(int(p["id"])) > 0
        ]
        for it in expiring:
            key = f"expire:{it['id']}:{today}"
            for uid in recipients:
                if _was_sent(conn, "item_expiring", key, uid):
                    continue
                exp = it.get("expires_at") or ""
                body = f"{it['name']} expires {exp}"
                res = push_db.send_to_user(
                    uid,
                    title="Expiring soon",
                    body=body,
                    url="/inventory/food",
                )
                if res["sent"] > 0:
                    _mark_sent(conn, "item_expiring", key, uid)
                    delivered += res["sent"]

    # --- Return windows closing within 3 days --------------------------------
    try:
        from inventory import db as inv_db
        inv_db.init_db()
        returning = inv_db.items_returnable_within(3)
    except Exception:
        returning = []
    if returning:
        recipients = [
            int(p["id"]) for p in chores_db.list_people()
            if push_db.count_subscriptions_for_user(int(p["id"])) > 0
        ]
        for it in returning:
            key = f"return:{it['id']}:{it.get('return_until') or ''}"
            for uid in recipients:
                if _was_sent(conn, "item_return", key, uid):
                    continue
                body = (
                    f"{it['name']} — return by "
                    f"{it.get('return_until') or 'soon'}"
                )
                res = push_db.send_to_user(
                    uid,
                    title="Return window closing",
                    body=body,
                    url="/inventory",
                )
                if res["sent"] > 0:
                    _mark_sent(conn, "item_return", key, uid)
                    delivered += res["sent"]

    # --- Warranties expiring within 14 days ----------------------------------
    try:
        warranties = inv_db.items_warranty_expiring_within(14)
    except Exception:
        warranties = []
    if warranties:
        recipients = [
            int(p["id"]) for p in chores_db.list_people()
            if push_db.count_subscriptions_for_user(int(p["id"])) > 0
        ]
        for it in warranties:
            key = f"warranty:{it['id']}:{it.get('warranty_until') or ''}"
            for uid in recipients:
                if _was_sent(conn, "item_warranty", key, uid):
                    continue
                body = (
                    f"{it['name']} — warranty until "
                    f"{it.get('warranty_until') or 'soon'}"
                )
                res = push_db.send_to_user(
                    uid,
                    title="Warranty expiring",
                    body=body,
                    url="/inventory",
                )
                if res["sent"] > 0:
                    _mark_sent(conn, "item_warranty", key, uid)
                    delivered += res["sent"]

    conn.close()
    return delivered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=["dev", "prod"], required=True)
    args = parser.parse_args()

    if args.env == "dev":
        root = "/opt/house-inventory"
    else:
        root = "/opt/gyst-prod"
    sys.path.insert(0, root)

    delivered = run()
    print(f"[reminders:{args.env}] delivered {delivered} push(es)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
