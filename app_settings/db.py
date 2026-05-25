"""Settings storage with at-rest encryption for sensitive values.

A single key-value table holds runtime configuration (LLM provider, API
keys, model names). Values flagged as encrypted are stored as Fernet
ciphertext using a master key kept at `config.MASTER_KEY_PATH` (chmod 600).
Plaintext is only ever held in memory at decrypt time.

Public API:
  init_db() — create schema, ensure master key exists
  get(key, default=None) — get plaintext value (auto-decrypts)
  set(key, value, *, encrypt=False) — store value, optionally encrypted
  is_set(key) — True if a non-empty value is stored (for "configured" UI)
  delete(key)
  set_with_default(key, value, *, encrypt=False) — only sets if not already set
"""

from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import contextmanager
from typing import Iterator, Optional

import config


# ---- Master key --------------------------------------------------------------
_master_key_cache: Optional[bytes] = None


def _get_master_key() -> bytes:
    """Read the Fernet master key, generating it on first run."""
    global _master_key_cache
    if _master_key_cache is not None:
        return _master_key_cache

    from cryptography.fernet import Fernet

    path = config.MASTER_KEY_PATH
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        path.write_bytes(key)
        # Lock down permissions — owner read/write only.
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    _master_key_cache = path.read_bytes()
    return _master_key_cache


def _encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    from cryptography.fernet import Fernet

    f = Fernet(_get_master_key())
    return f.encrypt(plaintext.encode("utf-8")).decode("ascii")


def _decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    from cryptography.fernet import Fernet, InvalidToken

    f = Fernet(_get_master_key())
    try:
        return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        # Master key changed or value corrupt — surface as empty so callers
        # can detect "not configured" rather than crash.
        return ""


# ---- DB layer ----------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.APP_SETTINGS_DB_PATH)
    conn.row_factory = sqlite3.Row
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
    config.APP_SETTINGS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _cursor() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT,
              encrypted INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
    # Lock down DB file permissions too.
    try:
        os.chmod(config.APP_SETTINGS_DB_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    # Touch the master key file so it exists with the right perms from the start.
    _get_master_key()


def get(key: str, default: Optional[str] = None) -> Optional[str]:
    """Return plaintext value, decrypting if needed. None if not set."""
    with _cursor() as conn:
        row = conn.execute(
            "SELECT value, encrypted FROM settings WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return default
    value = row["value"] or ""
    if row["encrypted"]:
        value = _decrypt(value)
    return value or default


def set(key: str, value: str, *, encrypt: bool = False) -> None:  # noqa: A001
    """Store a value. If `encrypt=True`, the value is Fernet-encrypted at rest."""
    stored = _encrypt(value) if encrypt else value
    with _cursor() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, encrypted, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
              value = excluded.value,
              encrypted = excluded.encrypted,
              updated_at = excluded.updated_at
            """,
            (key, stored, 1 if encrypt else 0),
        )


def set_with_default(key: str, value: str, *, encrypt: bool = False) -> None:
    """Set a value only if the key isn't already set."""
    with _cursor() as conn:
        row = conn.execute(
            "SELECT 1 FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row is not None:
            return
    set(key, value, encrypt=encrypt)


def is_set(key: str) -> bool:
    """True iff a non-empty value is stored."""
    with _cursor() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return bool(row and (row["value"] or "").strip())


def delete(key: str) -> None:
    with _cursor() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


# ---- Locale helpers (currency + timezone) ----------------------------------
# User-editable in Settings -> Appearance. Stored as plain rows in this
# table; defaults are baked here so a fresh install renders correctly
# before the user has touched anything.

_CURRENCY_SYMBOL = {
    "USD": "$",
    "CAD": "$",
    "EUR": "€",
    "GBP": "£",
    "AUD": "$",
    "NZD": "$",
    "JPY": "¥",
    "CHF": "CHF ",
    "MXN": "$",
    "BRL": "R$",
    "INR": "₹",
    "CNY": "¥",
    "SEK": "kr ",
    "NOK": "kr ",
    "DKK": "kr ",
    "ZAR": "R",
}

DEFAULT_CURRENCY = "CAD"
DEFAULT_TIMEZONE = "America/Halifax"


def get_currency() -> str:
    """ISO 4217 code for prices rendered in the UI + stored from
    scans. Default 'CAD'."""
    v = (get("currency_code") or "").strip().upper()
    return v if v else DEFAULT_CURRENCY


def set_currency(code: str) -> None:
    code = (code or "").strip().upper()
    if not code:
        return
    set("currency_code", code)


def currency_symbol(code: str | None = None) -> str:
    """One- or two-char display symbol for the given currency code,
    falling back to the code itself with a trailing space."""
    if code is None:
        code = get_currency()
    return _CURRENCY_SYMBOL.get(code.upper(), code.upper() + " ")


def get_timezone() -> str:
    """IANA timezone name for user-facing time displays. Default
    'America/Halifax'."""
    v = (get("timezone") or "").strip()
    return v if v else DEFAULT_TIMEZONE


def set_timezone(tz_name: str) -> None:
    tz_name = (tz_name or "").strip()
    if not tz_name:
        return
    # Validate before storing — bad zones would crash zoneinfo at
    # every lookup, which is worse than rejecting the change.
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz_name)
    except Exception:
        return
    set("timezone", tz_name)
