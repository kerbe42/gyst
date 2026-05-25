"""Push notification subscriptions + VAPID key bootstrap.

Web Push works like this:
 1. The browser asks for permission and registers a PushSubscription with
    the OS's push service (Mozilla autopush, Apple, FCM for Chrome, etc).
 2. The subscription is a JSON object containing an HTTPS endpoint URL +
    encryption keys (p256dh + auth). We store it in `push_subscriptions`.
 3. To send a push, we POST an encrypted payload to that endpoint, signed
    with our VAPID private key. pywebpush does the heavy lifting.

VAPID keys are an EC P-256 keypair we generate once and re-use forever.
They're how the push service knows the request came from this server.
The public half is shared with the browser at subscription time (this is
what `applicationServerKey` ends up being on the JS side); the private
half stays on the server.

All sensitive values (VAPID private key, the per-subscription auth keys)
are stored encrypted via app_settings.db's Fernet wrapper.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

import config
from app_settings import db as settings_db


# Setting keys for the VAPID keypair stored in app_settings.db.
SETTING_VAPID_PUBLIC = "vapid_public_key"
SETTING_VAPID_PRIVATE = "vapid_private_key"
SETTING_VAPID_SUBJECT = "vapid_subject"   # mailto: or https: URL


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.NOTIFICATIONS_DB_PATH)
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
    config.NOTIFICATIONS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _cursor() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS push_subscriptions (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL,
              endpoint TEXT NOT NULL UNIQUE,
              p256dh TEXT NOT NULL,
              auth TEXT NOT NULL,
              user_agent TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              last_used_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_push_user
                ON push_subscriptions(user_id);
            """
        )


# ---- VAPID key bootstrap -----------------------------------------------------
def _generate_vapid_keypair() -> tuple[str, str]:
    """Generate a fresh VAPID keypair. Returns (public_b64url, private_b64url).
    Both are URL-safe base64 of the raw EC P-256 coordinates expected by
    the Web Push standard."""
    import base64
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    priv = ec.generate_private_key(ec.SECP256R1())
    priv_num = priv.private_numbers().private_value
    priv_bytes = priv_num.to_bytes(32, "big")

    pub = priv.public_key()
    pub_bytes = pub.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    def b64url(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    return b64url(pub_bytes), b64url(priv_bytes)


def ensure_vapid_keys(default_subject: str = "mailto:admin@gyst.local") -> dict:
    """Ensure a VAPID keypair exists in app_settings; create one if not.
    Returns {public, private, subject} — the public key is what we hand to
    the browser; the private key stays on the server."""
    settings_db.init_db()
    public = settings_db.get(SETTING_VAPID_PUBLIC)
    private = settings_db.get(SETTING_VAPID_PRIVATE)
    subject = settings_db.get(SETTING_VAPID_SUBJECT) or default_subject
    if not public or not private:
        public, private = _generate_vapid_keypair()
        settings_db.set(SETTING_VAPID_PUBLIC, public)
        settings_db.set(SETTING_VAPID_PRIVATE, private, encrypt=True)
        if not settings_db.is_set(SETTING_VAPID_SUBJECT):
            settings_db.set(SETTING_VAPID_SUBJECT, default_subject)
        subject = default_subject
    return {"public": public, "private": private, "subject": subject}


# ---- Subscription CRUD -------------------------------------------------------
def upsert_subscription(
    user_id: int,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: Optional[str] = None,
) -> int:
    """Insert a subscription, or refresh an existing one keyed on endpoint."""
    init_db()
    with _cursor() as conn:
        cur = conn.execute(
            """
            INSERT INTO push_subscriptions
                (user_id, endpoint, p256dh, auth, user_agent)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                user_id=excluded.user_id,
                p256dh=excluded.p256dh,
                auth=excluded.auth,
                user_agent=excluded.user_agent
            """,
            (int(user_id), endpoint, p256dh, auth, (user_agent or "")[:200]),
        )
        return int(cur.lastrowid or 0)


def delete_subscription_by_endpoint(endpoint: str) -> None:
    with _cursor() as conn:
        conn.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,)
        )


def delete_subscriptions_for_user(user_id: int) -> int:
    with _cursor() as conn:
        cur = conn.execute(
            "DELETE FROM push_subscriptions WHERE user_id = ?",
            (int(user_id),),
        )
        return int(cur.rowcount or 0)


def list_subscriptions_for_user(user_id: int) -> list[dict]:
    init_db()
    with _cursor() as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, endpoint, p256dh, auth, user_agent,
                   created_at, last_used_at
            FROM push_subscriptions
            WHERE user_id = ?
            """,
            (int(user_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def count_subscriptions_for_user(user_id: int) -> int:
    init_db()
    with _cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        return int(row["n"]) if row else 0


def mark_used(endpoint: str) -> None:
    with _cursor() as conn:
        conn.execute(
            "UPDATE push_subscriptions SET last_used_at = datetime('now') "
            "WHERE endpoint = ?",
            (endpoint,),
        )


# ---- Send --------------------------------------------------------------------
def send_to_user(
    user_id: int,
    title: str,
    body: str = "",
    url: Optional[str] = None,
) -> dict:
    """Send a push notification to every subscription a user has. Returns
    {sent, failed, removed} counts. Subscriptions that 404/410 are pruned
    automatically (the push service signals the endpoint is dead)."""
    import sys
    from pywebpush import WebPushException, webpush

    vapid = ensure_vapid_keys()
    payload = json.dumps({"title": title, "body": body, "url": url or "/"})

    subs = list_subscriptions_for_user(user_id)
    sent = failed = removed = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {
                        "p256dh": sub["p256dh"],
                        "auth": sub["auth"],
                    },
                },
                data=payload,
                vapid_private_key=vapid["private"],
                vapid_claims={"sub": vapid["subject"]},
                ttl=3600,
            )
            mark_used(sub["endpoint"])
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None) if exc.response else None
            if status in (404, 410):
                delete_subscription_by_endpoint(sub["endpoint"])
                removed += 1
            else:
                failed += 1
                print(
                    f"[push] send failed status={status} sub={sub['id']}: {exc}",
                    file=sys.stderr,
                )
        except Exception as exc:
            failed += 1
            print(f"[push] unexpected error: {exc}", file=sys.stderr)
    return {"sent": sent, "failed": failed, "removed": removed}
