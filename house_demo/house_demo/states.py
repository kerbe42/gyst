"""State classes for House App pages.

Each page has its own State class managing its data and event handlers.
DB access goes through inventory.db and chores.db — those modules are
importable thanks to PYTHONPATH=/opt/house-inventory in the systemd unit.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, TypedDict

import reflex as rx

import config


def _is_safe_shared_photo_path(raw_path: str) -> Optional[Path]:
    """Validate a `gyst_shared_photo` cookie value before reading the file.

    Returns the resolved Path iff it lives strictly under
    ``config.PHOTOS_DIR / "shared"``. Returns None for empty input, path
    traversal (``../``), absolute paths outside that directory, symlink
    escapes, or anything else suspicious.

    Defense in depth: the cookie is set server-side with HttpOnly+Lax
    flags, but JS that runs in the page (e.g. via a future stored-XSS
    or a misbehaving extension) can still write a non-HttpOnly cookie
    of the same name. Without this check, an attacker could plant
    ``gyst_shared_photo=/etc/passwd`` and have the recognition pipeline
    exfiltrate the contents to the LLM provider. See CWE-22.
    """
    if not raw_path:
        return None
    try:
        p = Path(raw_path).resolve(strict=False)
        shared_root = (config.PHOTOS_DIR / "shared").resolve(strict=False)
        # relative_to raises ValueError if outside the prefix.
        p.relative_to(shared_root)
    except (ValueError, OSError):
        return None
    return p
from announcements import db as ann_db
from app_settings import db as settings_db
from appointments import db as appt_db
from chores import db as chores_db
from groceries import db as groc_db
from inventory import db as inv_db
from inventory import recognize
from meals import db as meals_db
from notes import db as notes_db
from assistant import chat as assistant_chat


# ---- Typed row shapes (so Reflex's Var system can introspect dict keys) ------

# ---- Restored helpers (re-added after refactor accidentally removed them) ---

def _save_oriented_jpeg(data: bytes, out_path: Path) -> None:
    """EXIF-orient and save raw upload bytes as JPEG. Pure-sync; meant to be
    called from `asyncio.to_thread` so it doesn't block the event loop.

    Raises ValueError on oversized or non-image input.
    """
    if not data:
        raise ValueError("Empty upload")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise ValueError(
            f"Upload too large ({len(data)} bytes, max {_MAX_UPLOAD_BYTES})"
        )
    from PIL import Image, ImageOps

    # Pillow's built-in defense against decompression bombs.
    Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as raw:
            raw.verify()  # cheap header sanity check; raises on garbage
        # `verify()` consumes the image; reopen for actual processing.
        img = ImageOps.exif_transpose(
            Image.open(io.BytesIO(data))
        ).convert("RGB")
    except Image.DecompressionBombError as exc:
        raise ValueError("Image too large to process") from exc
    if img.width * img.height > _MAX_IMAGE_PIXELS:
        raise ValueError("Image too large to process")
    img.save(out_path, "JPEG", quality=92)

def _safe_error(exc: Exception, generic: str) -> str:
    """Return a user-safe error message. ValueError typically carries our
    own validated messages and is safe to display; everything else gets
    masked with `generic` and the real traceback is dumped to stderr for
    server-side debugging."""
    import sys
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.stderr.flush()
    if isinstance(exc, ValueError):
        return str(exc)
    return generic

def _friendly_llm_error(exc: Exception, *, action: str) -> str:
    """Translate a raw SDK exception into a short, human-friendly sentence
    suitable for the in-app red callout. Falls back to the exception type
    name when we don't recognize the failure mode."""
    code = getattr(exc, "status_code", None)
    msg = str(exc).lower()
    if code in (429,) or "rate_limit" in msg or "rate limit" in msg:
        return (
            f"The vision API is rate-limiting us right now. "
            f"Wait a few seconds and tap Scan items again."
        )
    if code in (529,) or "overloaded" in msg:
        return (
            f"The vision API is overloaded right now (this happens on busy "
            f"days). Wait 30 seconds and tap Scan items again, or switch "
            f"the provider in Settings → API."
        )
    if code in (502, 503, 504):
        return (
            f"The vision API is briefly unreachable. Try again in a moment."
        )
    if code == 401 or "authentication" in msg or "api_key" in msg:
        return (
            "API key looks invalid. Open Settings → API and re-enter the key "
            "for the selected provider."
        )
    if code == 400 and "model" in msg:
        return (
            "The selected model name isn't accepted by the provider. "
            "Open Settings → API and pick a valid model."
        )
    # Fallback: short type name, no raw JSON.
    return f"{action.capitalize()} failed: {type(exc).__name__}."

def _format_value(v) -> str:
    """Format an estimated value as $X.XX, or '' if unknown/zero. Re-added
    after a refactor accidentally removed it; _enrich_item_row calls it
    to compute the `value_display` field rendered by the browse page."""
    try:
        f = float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return ""
    if f <= 0:
        return ""
    return f"${f:,.2f}"



def _enrich_item_row(row: dict) -> dict:
    """Add derived UI fields (URLs, formatted value, bool flags)."""
    row["photo_url"] = _photo_url(row.get("photo_path", ""))
    item_id = row.get("id")
    row["crop_url"] = (
        f"/photo_crop/{int(item_id)}" if item_id else row["photo_url"]
    )
    row["for_sale_bool"] = bool(row.get("for_sale"))
    row["value_display"] = _format_value(row.get("estimated_value"))
    # New: explicit string fields so the Reflex Var system can dereference
    # them in the template, plus a single bool for "currently loaned out".
    row["expires_at"] = row.get("expires_at") or ""
    row["loaned_to_name"] = row.get("loaned_to_name") or ""
    row["loaned_at"] = row.get("loaned_at") or ""
    row["loan_notes"] = row.get("loan_notes") or ""
    row["is_loaned"] = bool(row.get("loaned_to_name") or row.get("loaned_to_id"))
    return row

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_MAX_IMAGE_PIXELS = 25_000_000

class ItemRow(TypedDict, total=False):
    """A row shown in Inventory Search or Browse."""

    id: int
    name: str
    category: str
    quantity: int
    detector_count: int
    boxes: list
    for_sale: int
    for_sale_bool: bool
    estimated_value: float
    value_display: str  # formatted $X.XX or "" if unknown
    created_at: str
    deleted_at: str  # ISO timestamp; only populated for trash rows
    photo_path: str
    photo_url: str  # full photo
    crop_url: str  # photo cropped to this item's bounding box
    room: str
    photo_id: int
    photo_taken_at: str
    expires_at: str
    loaned_to_name: str
    loaned_at: str
    loan_notes: str
    is_loaned: bool


class CapturedItem(TypedDict):
    """A row in the Capture page's saved-item summary. After upload, each
    item is auto-committed to inventory; `item_id` is the DB row so the
    user can delete it individually right from the summary."""

    idx: int
    item_id: int             # 0 if not yet saved / already deleted
    name: str
    category: str
    quantity: int
    detector_count: int
    boxes: list
    keep: bool
    for_sale: bool
    estimated_value: float


class TaskRow(TypedDict, total=False):
    """A row shown on the Tasks page."""

    id: int
    title: str
    description: str
    assigned_to: int
    due_date: str
    completed: int
    completed_bool: bool
    completed_at: str
    created_at: str
    assignee_name: str
    assignee_color: str
    due_display: str
    assignee_label: str
    description_text: str
    completion_photo_path: str
    completion_photo_url: str
    has_photo: bool


class PersonRow(TypedDict, total=False):
    """A row shown on the People page (and used elsewhere as a list)."""

    id: int
    name: str
    color: str
    created_at: str
    task_count: int


class RoomSummary(TypedDict):
    """A row in the per-room totals strip on the Browse page."""

    room: str
    count: int


# ---- UI state (shared chrome) ------------------------------------------------
class UIState(rx.State):
    """Layout chrome state — mobile drawer + collapsible sidebar sections."""

    sidebar_open: bool = False
    inventory_section_open: bool = False
    chores_section_open: bool = False
    groceries_section_open: bool = False
    meals_section_open: bool = False
    appointments_section_open: bool = False
    admin_section_open: bool = False

    @rx.event
    def toggle_sidebar(self):
        self.sidebar_open = not self.sidebar_open

    @rx.event
    def close_sidebar(self):
        self.sidebar_open = False

    @rx.event
    def toggle_inventory_section(self):
        self.inventory_section_open = not self.inventory_section_open

    @rx.event
    def toggle_chores_section(self):
        self.chores_section_open = not self.chores_section_open

    @rx.event
    def toggle_groceries_section(self):
        self.groceries_section_open = not self.groceries_section_open

    @rx.event
    def toggle_meals_section(self):
        self.meals_section_open = not self.meals_section_open

    @rx.event
    def toggle_appointments_section(self):
        self.appointments_section_open = not self.appointments_section_open

    @rx.event
    def toggle_admin_section(self):
        self.admin_section_open = not self.admin_section_open


# ---- Settings: users & rooms management --------------------------------------
class SettingsUserRow(TypedDict, total=False):
    id: int
    name: str
    initial: str        # first letter, uppercase — used in the avatar pill
    color: str
    email: str
    username: str
    has_username: bool
    is_admin: int
    is_admin_bool: bool
    task_count: int


class SettingsRoomRow(TypedDict, total=False):
    id: int
    name: str
    sort_order: int


class AuditRow(TypedDict, total=False):
    id: int
    actor_name: str
    action: str
    target: str
    detail: str
    ip: str
    created_at: str


class GroceryMatchRow(TypedDict):
    id: int
    name: str


class HistoryRow(TypedDict, total=False):
    kind: str
    text: str
    ts_rel: str
    actor: str


class SettingsState(rx.State):
    """Settings page state — manages users and rooms."""

    users: list[SettingsUserRow] = []
    rooms: list[SettingsRoomRow] = []

    # Add-user form
    new_user_name: str = ""
    new_user_email: str = ""
    new_user_admin: bool = False
    user_error: str = ""

    # Add-room form
    new_room_name: str = ""
    room_error: str = ""

    # API tab — provider selection + write-only key management
    api_provider: str = recognize.DEFAULT_PROVIDER
    claude_model: str = recognize.DEFAULT_CLAUDE_MODEL
    openai_model: str = recognize.DEFAULT_OPENAI_MODEL
    anthropic_key_input: str = ""
    openai_key_input: str = ""
    anthropic_key_set: bool = False
    openai_key_set: bool = False
    enable_detector: bool = recognize.DEFAULT_ENABLE_DETECTOR
    api_message: str = ""
    api_error: str = ""

    # Audit log — populated on Settings page load.
    audit_rows: list[AuditRow] = []

    # iCal subscription URL — empty until the user opens the section.
    ical_url: str = ""

    # Manage-user dialog (per-user editing of profile + credentials +
    # permissions). `managing_user_id` doubles as the open/closed flag —
    # 0 means closed.
    managing_user_id: int = 0
    managing_user_name: str = ""     # display name we read INTO the form
    managing_name: str = ""          # editable display name
    managing_email: str = ""
    managing_username: str = ""
    managing_has_username: bool = False
    managing_password: str = ""
    managing_password_confirm: str = ""
    managing_is_admin: bool = False
    managing_can_read_inventory: bool = True
    managing_can_write_inventory: bool = True
    managing_can_read_chores: bool = True
    managing_can_write_chores: bool = True
    manage_error: str = ""
    manage_success: str = ""

    # ---- Locale settings (currency + timezone) -----------------------------
    current_currency: str = "CAD"
    current_timezone: str = "America/Halifax"

    @rx.event
    def reload_locale_settings(self):
        try:
            from app_settings import db as _sdb
            self.current_currency = _sdb.get_currency()
            self.current_timezone = _sdb.get_timezone()
        except Exception:
            pass

    @rx.event
    def set_locale_currency(self, code: str):
        from app_settings import db as _sdb
        _sdb.set_currency(code)
        self.current_currency = _sdb.get_currency()
        return rx.toast.success(f"Currency set to {self.current_currency}.")

    @rx.event
    def set_locale_timezone(self, tz_name: str):
        from app_settings import db as _sdb
        _sdb.set_timezone(tz_name)
        new_tz = _sdb.get_timezone()
        self.current_timezone = new_tz
        if new_tz == tz_name:
            return rx.toast.success(f"Time zone set to {new_tz}.")
        return rx.toast.error(f"'{tz_name}' isn't a valid zone. Keeping {new_tz}.")

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self, admin=True)
        if redir is not None:
            return redir
        chores_db.init_db()
        inv_db.init_db()
        settings_db.init_db()
        self._refresh_users()
        self._refresh_rooms()
        self._load_api_settings()
        self._refresh_audit()

    def _refresh_audit(self):
        raw = chores_db.list_audit(limit=200)
        self.audit_rows = [
            {
                "id": int(r["id"]),
                "actor_name": r.get("actor_name") or "—",
                "action": r["action"],
                "target": r.get("target") or "",
                "detail": r.get("detail") or "",
                "ip": r.get("ip") or "",
                "created_at": r["created_at"],
            }
            for r in raw
        ]

    @rx.event
    def refresh_audit(self):
        self._refresh_audit()

    # ---- iCal subscription URL --------------------------------------
    @rx.event
    async def show_ical_url(self):
        auth = await self.get_state(AuthState)
        if not auth.current_user_id:
            return
        token = chores_db.ensure_ical_token(int(auth.current_user_id))
        origin = (
            os.environ.get("GYST_PUBLIC_ORIGIN")
            or "http://gyst.local:3001"
        )
        self.ical_url = f"{origin}/calendar.ics?token={token}"

    @rx.event
    async def rotate_ical(self):
        auth = await self.get_state(AuthState)
        if not auth.current_user_id:
            return
        token = chores_db.rotate_ical_token(int(auth.current_user_id))
        chores_db.log_audit(
            int(auth.current_user_id), auth.current_user_name,
            "settings.ical_rotate", target=str(auth.current_user_id),
        )
        origin = (
            os.environ.get("GYST_PUBLIC_ORIGIN")
            or "http://gyst.local:3001"
        )
        self.ical_url = f"{origin}/calendar.ics?token={token}"
        return rx.toast.success(
            "iCal URL rotated. Re-subscribe on each device.",
            duration=4000,
        )

    # ---- API settings -----
    @rx.var
    def api_provider_options(self) -> list[str]:
        return ["claude", "openai"]

    def _load_api_settings(self):
        self.api_provider = (
            settings_db.get(recognize.SETTING_PROVIDER, recognize.DEFAULT_PROVIDER)
            or recognize.DEFAULT_PROVIDER
        )
        self.claude_model = (
            settings_db.get(
                recognize.SETTING_CLAUDE_MODEL, recognize.DEFAULT_CLAUDE_MODEL
            )
            or recognize.DEFAULT_CLAUDE_MODEL
        )
        self.openai_model = (
            settings_db.get(
                recognize.SETTING_OPENAI_MODEL, recognize.DEFAULT_OPENAI_MODEL
            )
            or recognize.DEFAULT_OPENAI_MODEL
        )
        self.anthropic_key_set = settings_db.is_set(recognize.SETTING_ANTHROPIC_KEY)
        self.openai_key_set = settings_db.is_set(recognize.SETTING_OPENAI_KEY)
        self.enable_detector = recognize.detector_enabled()
        self.anthropic_key_input = ""
        self.openai_key_input = ""
        self.api_message = ""
        self.api_error = ""

    @rx.event
    def set_api_provider(self, value: str):
        self.api_provider = value
        self.api_message = ""
        self.api_error = ""

    @rx.event
    def set_claude_model(self, value: str):
        self.claude_model = value

    @rx.event
    def set_openai_model(self, value: str):
        self.openai_model = value

    @rx.event
    def set_anthropic_key_input(self, value: str):
        self.anthropic_key_input = value

    @rx.event
    def set_openai_key_input(self, value: str):
        self.openai_key_input = value

    @rx.event
    def set_enable_detector(self, value: bool):
        self.enable_detector = bool(value)

    @rx.event
    async def save_api_settings(self):
        """Persist provider + model selection (always) and any newly-entered
        API keys (only if non-empty). Keys are encrypted at rest."""
        try:
            settings_db.set(recognize.SETTING_PROVIDER, self.api_provider)
            settings_db.set(
                recognize.SETTING_CLAUDE_MODEL,
                self.claude_model.strip() or recognize.DEFAULT_CLAUDE_MODEL,
            )
            settings_db.set(
                recognize.SETTING_OPENAI_MODEL,
                self.openai_model.strip() or recognize.DEFAULT_OPENAI_MODEL,
            )
            settings_db.set(
                recognize.SETTING_ENABLE_DETECTOR,
                "1" if self.enable_detector else "0",
            )
            if self.anthropic_key_input.strip():
                settings_db.set(
                    recognize.SETTING_ANTHROPIC_KEY,
                    self.anthropic_key_input.strip(),
                    encrypt=True,
                )
            if self.openai_key_input.strip():
                settings_db.set(
                    recognize.SETTING_OPENAI_KEY,
                    self.openai_key_input.strip(),
                    encrypt=True,
                )
        except Exception as exc:
            self.api_error = _safe_error(exc, "Could not save API settings.")
            self.api_message = ""
            return
        self.api_error = ""
        self.api_message = ""
        auth = await self.get_state(AuthState)
        chores_db.log_audit(
            auth.current_user_id, auth.current_user_name,
            "settings.api_save", target=self.api_provider,
            detail=(
                f"new_anthropic_key={bool(self.anthropic_key_input.strip())} "
                f"new_openai_key={bool(self.openai_key_input.strip())} "
                f"detector={'on' if self.enable_detector else 'off'}"
            ),
        )
        self._load_api_settings()
        return rx.toast.success("API settings saved", duration=3500)

    @rx.event
    async def clear_anthropic_key(self):
        settings_db.delete(recognize.SETTING_ANTHROPIC_KEY)
        auth = await self.get_state(AuthState)
        chores_db.log_audit(
            auth.current_user_id, auth.current_user_name,
            "settings.api_key_clear", target="anthropic",
        )
        self.api_message = ""
        self.api_error = ""
        self._load_api_settings()
        return rx.toast.info("Anthropic key cleared", duration=3500)

    @rx.event
    async def clear_openai_key(self):
        settings_db.delete(recognize.SETTING_OPENAI_KEY)
        auth = await self.get_state(AuthState)
        chores_db.log_audit(
            auth.current_user_id, auth.current_user_name,
            "settings.api_key_clear", target="openai",
        )
        self.api_message = ""
        self.api_error = ""
        self._load_api_settings()
        return rx.toast.info("OpenAI key cleared", duration=3500)

    # ---- Users -----
    @rx.event
    def set_new_user_name(self, value: str):
        self.new_user_name = value
        if self.user_error:
            self.user_error = ""

    @rx.event
    def set_new_user_email(self, value: str):
        self.new_user_email = value

    @rx.event
    def set_new_user_admin(self, value: bool):
        self.new_user_admin = value

    @rx.event
    async def add_user(self):
        name = self.new_user_name.strip()
        if not name:
            self.user_error = "Name can't be empty."
            return
        try:
            chores_db.add_person(
                name=name,
                email=self.new_user_email.strip() or None,
                is_admin=self.new_user_admin,
            )
        except Exception as exc:
            self.user_error = _safe_error(exc, "Could not add user.")
            return
        auth = await self.get_state(AuthState)
        chores_db.log_audit(
            auth.current_user_id, auth.current_user_name,
            "user.add", target=name,
            detail=f"admin={self.new_user_admin}",
        )
        self.new_user_name = ""
        self.new_user_email = ""
        self.new_user_admin = False
        self.user_error = ""
        self._refresh_users()
        return rx.toast.success(f"Added {name}", duration=3000)

    @rx.event
    def toggle_admin(self, user_id: int):
        for u in self.users:
            if int(u["id"]) == int(user_id):
                new_admin = not bool(u.get("is_admin_bool"))
                chores_db.update_person(
                    int(user_id), is_admin=new_admin,
                )
                break
        self._refresh_users()

    @rx.event
    async def delete_user(self, user_id: int):
        target = next(
            (u["name"] for u in self.users if int(u["id"]) == int(user_id)),
            str(user_id),
        )
        chores_db.delete_person(int(user_id))
        auth = await self.get_state(AuthState)
        chores_db.log_audit(
            auth.current_user_id, auth.current_user_name,
            "user.delete", target=target,
        )
        self._refresh_users()
        return rx.toast.info("User deleted", duration=3000)

    def _refresh_users(self):
        raw = chores_db.list_people()
        out: list[SettingsUserRow] = []
        for u in raw:
            name = u["name"] or ""
            out.append(
                {
                    "id": int(u["id"]),
                    "name": name,
                    "initial": (name.strip()[:1] or "?").upper(),
                    "color": u["color"] or chores_db.derive_color(u["id"]),
                    "email": u.get("email") or "",
                    "username": u.get("username") or "",
                    "has_username": bool(u.get("username")),
                    "is_admin": int(u.get("is_admin") or 0),
                    "is_admin_bool": bool(u.get("is_admin")),
                    "task_count": chores_db.person_task_count(int(u["id"])),
                }
            )
        self.users = out

    # ---- Manage-user dialog -----
    @rx.event
    def open_manage(self, user_id: int):
        """Load a user into the management dialog and open it."""
        user = chores_db.get_user_by_id(int(user_id))
        if not user:
            return
        self.managing_user_id = int(user["id"])
        self.managing_user_name = user["name"]
        self.managing_name = user["name"]
        self.managing_email = user.get("email") or ""
        self.managing_username = user.get("username") or ""
        self.managing_has_username = bool(user.get("username"))
        self.managing_password = ""
        self.managing_password_confirm = ""
        self.managing_is_admin = bool(user.get("is_admin"))
        self.managing_can_read_inventory = bool(
            user.get("can_read_inventory", 1)
        )
        self.managing_can_write_inventory = bool(
            user.get("can_write_inventory", 1)
        )
        self.managing_can_read_chores = bool(user.get("can_read_chores", 1))
        self.managing_can_write_chores = bool(user.get("can_write_chores", 1))
        self.manage_error = ""
        self.manage_success = ""

    @rx.event
    def close_manage(self):
        self.managing_user_id = 0
        self.managing_password = ""
        self.managing_password_confirm = ""
        self.manage_error = ""
        self.manage_success = ""

    @rx.event
    def handle_manage_open_change(self, is_open: bool):
        # Fires when the dialog is closed via overlay click / escape.
        if not is_open:
            self.close_manage()

    @rx.event
    def set_managing_name(self, value: str):
        self.managing_name = value

    @rx.event
    def set_managing_email(self, value: str):
        self.managing_email = value

    @rx.event
    def set_managing_username(self, value: str):
        self.managing_username = value

    @rx.event
    def set_managing_password(self, value: str):
        self.managing_password = value

    @rx.event
    def set_managing_password_confirm(self, value: str):
        self.managing_password_confirm = value

    @rx.event
    def set_managing_is_admin(self, value: bool):
        self.managing_is_admin = value

    @rx.event
    def set_managing_can_read_inventory(self, value: bool):
        self.managing_can_read_inventory = value

    @rx.event
    def set_managing_can_write_inventory(self, value: bool):
        self.managing_can_write_inventory = value

    @rx.event
    def set_managing_can_read_chores(self, value: bool):
        self.managing_can_read_chores = value

    @rx.event
    def set_managing_can_write_chores(self, value: bool):
        self.managing_can_write_chores = value

    @rx.event
    async def save_profile(self):
        """Save the user's display name + email + admin flag."""
        if not self.managing_user_id:
            return
        name = self.managing_name.strip()
        if not name:
            self.manage_error = "Name can't be empty."
            return
        try:
            chores_db.update_person(
                self.managing_user_id,
                name=name,
                email=self.managing_email,
                is_admin=self.managing_is_admin,
            )
        except Exception as exc:
            self.manage_error = _safe_error(exc, "Could not save profile.")
            return
        auth = await self.get_state(AuthState)
        chores_db.log_audit(
            auth.current_user_id, auth.current_user_name,
            "user.profile_update", target=name,
            detail=f"email_set={bool(self.managing_email)} "
                   f"admin={self.managing_is_admin}",
        )
        self.manage_error = ""
        self.manage_success = ""
        self.managing_user_name = name
        self._refresh_users()
        return rx.toast.success(f"Profile saved for {name}", duration=3500)

    @rx.event
    async def save_credentials(self):
        """Set or update the target user's username and (optionally) password.

        Username is always stored lowercased and matched case-insensitively
        on login. Password is optional on this save — if both password
        fields are empty, only the username is rotated. If either is set,
        both must match and meet the length floor.

        Password is never stored in plaintext — it's hashed immediately and
        only the hash hits the DB.
        """
        if not self.managing_user_id:
            return
        username = (self.managing_username or "").strip()
        if not username:
            self.manage_error = "Username can't be empty."
            return

        # Password handling: blank = leave alone; set = validate & rotate.
        new_password: Optional[str] = None
        if self.managing_password or self.managing_password_confirm:
            if len(self.managing_password) < 8:
                self.manage_error = (
                    "Password must be at least 8 characters."
                )
                return
            if self.managing_password != self.managing_password_confirm:
                self.manage_error = "Passwords don't match."
                return
            new_password = self.managing_password

        try:
            chores_db.set_user_credentials(
                self.managing_user_id, username, new_password,
            )
        except ValueError as exc:
            self.manage_error = str(exc)
            return
        except Exception as exc:
            self.manage_error = _safe_error(exc, "Could not save credentials.")
            return

        auth = await self.get_state(AuthState)
        chores_db.log_audit(
            auth.current_user_id, auth.current_user_name,
            "user.credentials_update", target=username,
            detail=(
                "username+password" if new_password else "username only"
            ),
        )
        self.manage_error = ""
        self.manage_success = ""
        self.managing_has_username = True
        # Clear password fields immediately — never re-show.
        self.managing_password = ""
        self.managing_password_confirm = ""
        self._refresh_users()
        return rx.toast.success(
            "Credentials updated" if new_password else "Username updated",
            duration=3500,
        )

    @rx.event
    async def save_permissions(self):
        if not self.managing_user_id:
            return
        try:
            chores_db.set_permissions(
                self.managing_user_id,
                is_admin=self.managing_is_admin,
                can_read_inventory=self.managing_can_read_inventory,
                can_write_inventory=self.managing_can_write_inventory,
                can_read_chores=self.managing_can_read_chores,
                can_write_chores=self.managing_can_write_chores,
            )
        except Exception as exc:
            self.manage_error = _safe_error(exc, "Could not save credentials.")
            return
        auth = await self.get_state(AuthState)
        chores_db.log_audit(
            auth.current_user_id, auth.current_user_name,
            "user.permissions_update", target=self.managing_user_name,
            detail=(
                f"admin={self.managing_is_admin} "
                f"inv_r={self.managing_can_read_inventory} "
                f"inv_w={self.managing_can_write_inventory} "
                f"chr_r={self.managing_can_read_chores} "
                f"chr_w={self.managing_can_write_chores}"
            ),
        )
        self.manage_error = ""
        self.manage_success = ""
        self._refresh_users()
        return rx.toast.success("Permissions saved", duration=3500)

    # ---- Rooms -----
    @rx.event
    def set_new_room_name(self, value: str):
        self.new_room_name = value
        if self.room_error:
            self.room_error = ""

    @rx.event
    def add_room(self):
        name = self.new_room_name.strip().lower()
        if not name:
            self.room_error = "Room name can't be empty."
            return
        try:
            inv_db.add_room(name)
        except Exception as exc:
            self.room_error = _safe_error(exc, "Could not add room.")
            return
        self.new_room_name = ""
        self.room_error = ""
        self._refresh_rooms()
        return rx.toast.success(f"Added room: {name}", duration=3000)

    @rx.event
    def delete_room(self, room_id: int):
        inv_db.delete_room(int(room_id))
        self._refresh_rooms()
        return rx.toast.info("Room deleted", duration=3000)

    @rx.event
    def move_room_up(self, room_id: int):
        idx = next(
            (i for i, r in enumerate(self.rooms) if int(r["id"]) == int(room_id)),
            -1,
        )
        if idx <= 0:
            return
        a, b = self.rooms[idx - 1], self.rooms[idx]
        inv_db.update_room(int(a["id"]), a["name"], idx)
        inv_db.update_room(int(b["id"]), b["name"], idx - 1)
        self._refresh_rooms()

    @rx.event
    def move_room_down(self, room_id: int):
        idx = next(
            (i for i, r in enumerate(self.rooms) if int(r["id"]) == int(room_id)),
            -1,
        )
        if idx < 0 or idx >= len(self.rooms) - 1:
            return
        a, b = self.rooms[idx], self.rooms[idx + 1]
        inv_db.update_room(int(a["id"]), a["name"], idx + 1)
        inv_db.update_room(int(b["id"]), b["name"], idx)
        self._refresh_rooms()

    def _refresh_rooms(self):
        raw = inv_db.list_rooms()
        self.rooms = [
            {
                "id": int(r["id"]),
                "name": r["name"],
                "sort_order": int(r["sort_order"]),
            }
            for r in raw
        ]


# ---- Global undo snack -------------------------------------------------------
# One singleton state holds the last destructive action across all domains.
# Pages call `await UndoState.arm(kind, payload, label)` after deleting,
# the layout renders a fixed-bottom snack with an "Undo" button, and
# `do_undo()` dispatches to the right restore handler based on `kind`.
class UndoState(rx.State):
    kind: str = ""        # "inventory" | "task" | "grocery" | "meal" | "note" | "appointment" | "recipe" | "announcement"
    label: str = ""       # human-readable banner text
    payload: dict = {}    # whatever the restore handler needs
    seq: int = 0          # bumped on each arm — client-side dismiss timer keys off this

    def arm(self, kind: str, payload: dict, label: str) -> None:
        """Plain mutator (not an event) so other states can populate the
        snack inline after a destructive action via `get_state`."""
        self.kind = kind
        self.payload = payload or {}
        self.label = label
        self.seq = (self.seq or 0) + 1

    @rx.event
    def dismiss(self):
        self.kind = ""
        self.label = ""
        self.payload = {}

    @rx.event
    async def do_undo(self):
        """Reverse the last destructive action, then clear state."""
        kind = self.kind
        payload = self.payload or {}
        # Clear early so a slow restore can't show two snacks.
        self.kind = ""
        self.label = ""
        self.payload = {}

        try:
            if kind == "inventory":
                # Soft-delete: just clear deleted_at.
                inv_db.restore_item(int(payload.get("id", 0)))
            elif kind == "task":
                chores_db.add_task(
                    title=payload.get("title", ""),
                    description=payload.get("description"),
                    assigned_to=payload.get("assigned_to"),
                    due_date=payload.get("due_date"),
                    recurrence=payload.get("recurrence"),
                    parent_task_id=payload.get("parent_task_id"),
                )
            elif kind == "grocery_recon":
                # Revert auto-ticks from a receipt-driven reconciliation.
                for gid in payload.get("ids") or []:
                    try:
                        groc_db.set_purchased(int(gid), False)
                    except Exception:
                        pass
            elif kind == "grocery":
                groc_db.add_grocery(
                    name=payload.get("name", ""),
                    quantity=payload.get("quantity"),
                    notes=payload.get("notes"),
                    from_meal_id=payload.get("from_meal_id"),
                )
            elif kind == "meal":
                meals_db.add_meal(
                    name=payload.get("name", ""),
                    meal_date=payload.get("meal_date"),
                    meal_type=payload.get("meal_type"),
                    notes=payload.get("notes"),
                    ingredients=payload.get("ingredients") or [],
                )
            elif kind == "note":
                notes_db.add_note(
                    title=payload.get("title", ""),
                    body=payload.get("body"),
                    author_id=payload.get("author_id"),
                    pinned=bool(payload.get("pinned")),
                )
            elif kind == "appointment":
                appt_db.add_appointment(
                    title=payload.get("title", ""),
                    appointment_at=payload.get("appointment_at", ""),
                    location=payload.get("location"),
                    notes=payload.get("notes"),
                    for_person=payload.get("for_person"),
                    recurrence=payload.get("recurrence"),
                )
            elif kind == "recipe":
                meals_db.add_recipe(
                    name=payload.get("name", ""),
                    ingredients=payload.get("ingredients") or [],
                )
            elif kind == "announcement":
                ann_db.add_announcement(
                    title=payload.get("title", ""),
                    body=payload.get("body"),
                    posted_by=payload.get("posted_by"),
                    pinned=bool(payload.get("pinned")),
                )
        except Exception as exc:
            import sys, traceback
            traceback.print_exc(file=sys.stderr)
            return rx.toast.error(
                "Undo failed — the row may already be restored.",
                duration=3500,
            )
        return rx.toast.success("Restored.", duration=2500)


# ---- Login throttle ----------------------------------------------------------
# Simple in-process per-username throttle. Lives for the lifetime of the
# Reflex process — fine for a single-instance home deployment. After
# `_LOGIN_MAX_ATTEMPTS` failures within `_LOGIN_WINDOW_S`, the username is
# locked for `_LOGIN_LOCKOUT_S` seconds.
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_S = 300       # 5-minute rolling window
_LOGIN_LOCKOUT_S = 900      # 15-minute lockout
_login_attempts: dict[str, list[float]] = {}
_login_lockouts: dict[str, float] = {}


def _login_check(username: str) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds). Trims stale attempts."""
    import time as _t

    key = username.lower()
    now = _t.time()
    until = _login_lockouts.get(key, 0.0)
    if until > now:
        return False, int(until - now)
    # Lockout expired — clean up so the user starts fresh.
    if until and until <= now:
        _login_lockouts.pop(key, None)
        _login_attempts.pop(key, None)
    return True, 0


def _login_record_failure(username: str) -> None:
    import time as _t

    key = username.lower()
    now = _t.time()
    attempts = [
        t for t in _login_attempts.get(key, []) if now - t < _LOGIN_WINDOW_S
    ]
    attempts.append(now)
    _login_attempts[key] = attempts
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        _login_lockouts[key] = now + _LOGIN_LOCKOUT_S


def _login_record_success(username: str) -> None:
    _login_attempts.pop(username.lower(), None)
    _login_lockouts.pop(username.lower(), None)


# ---- Authentication ----------------------------------------------------------


# ---- Cross-state auth helpers ------------------------------------------------
# Module-level so any State.on_load can: `redir = await _require_auth(self,
# read="chores")`. These were briefly deleted during a refactor — keep them
# here as plain module functions.
async def _require_auth(state, *, read: str | None = None, admin: bool = False):
    """Check auth from any other state's event handler.

    Returns rx.redirect(...) if access denied, None if allowed.
    """
    auth = await state.get_state(AuthState)
    if not auth.is_authed:
        if not auth.hydrate_from_cookie():
            return rx.redirect("/login")
    if admin and not auth.is_admin:
        return rx.redirect("/")
    if read == "inventory" and not auth.can_read_inventory:
        return rx.redirect("/")
    if read == "chores" and not auth.can_read_chores:
        return rx.redirect("/")
    return None


async def _require_write(state, module: str) -> bool:
    """Check write permission. Returns True if allowed, False otherwise."""
    auth = await state.get_state(AuthState)
    if module == "inventory":
        return bool(auth.is_authed and auth.can_write_inventory)
    if module == "chores":
        return bool(auth.is_authed and auth.can_write_chores)
    # Strongman is single-athlete / household-shared like meals & notes: any
    # authenticated member may log training and nutrition. (Destructive ops
    # like a full reset gate on admin separately.)
    if module == "strongman":
        return bool(auth.is_authed)
    return False


def _photo_url(path_str: str) -> str:
    """Convert a stored photo path into a /photo/<filename> URL."""
    if not path_str:
        return ""
    return f"/photo/{os.path.basename(path_str)}"


class AuthState(rx.State):
    """Tracks the logged-in user and their permissions for the active session."""

    # Cookie-backed session token. When set, on_load can re-hydrate the
    # user from the DB without requiring them to log in again.
    #
    # `secure=True` only when the public origin is HTTPS — dev (port 3001
    # over plain HTTP) needs secure=False or the browser drops the cookie.
    #
    # Cookie name is namespaced per environment so dev and prod (which
    # share the same hostname) don't overwrite each other's session in
    # the shared cookie jar. The `GYST_ENV` env var is set to "dev" on
    # the dev systemd unit and is absent on prod (which keeps the original
    # cookie name so existing prod users stay signed in).
    session_token: str = rx.Cookie(
        "",
        name=(
            "house_session_" + os.environ["GYST_ENV"]
            if os.environ.get("GYST_ENV")
            else "house_session"
        ),
        max_age=30 * 24 * 3600,  # 30 days
        same_site="lax",
        path="/",
        secure=os.environ.get("GYST_PUBLIC_ORIGIN", "").startswith("https://"),
    )

    current_user_id: int = 0
    current_user_name: str = ""
    is_authed: bool = False
    is_admin: bool = False
    can_read_inventory: bool = False
    can_write_inventory: bool = False
    can_read_chores: bool = False
    can_write_chores: bool = False

    # Login form
    login_username: str = ""
    login_password: str = ""
    login_error: str = ""

    @rx.event
    def hydrate_from_cookie(self):
        """Called by `_require_auth` if we appear unauthed but have a cookie.
        Returns True if we restored a session, False otherwise.
        """
        if self.is_authed:
            return True
        token = (self.session_token or "").strip()
        if not token:
            return False
        user = chores_db.validate_session(token)
        if user:
            self._apply(user)
            return True
        # Token was invalid — clear it so we don't keep retrying.
        self.session_token = ""
        return False

    # First-run setup form
    setup_name: str = ""
    setup_username: str = ""
    setup_password: str = ""
    setup_password_confirm: str = ""
    setup_error: str = ""

    @rx.var
    def needs_setup(self) -> bool:
        chores_db.init_db()
        return not chores_db.has_any_authed_users()

    def _client_ip(self) -> str:
        """Best-effort client IP for audit logging. Looks at the standard
        X-Forwarded-For header that Caddy populates, then falls back to
        the direct peer."""
        try:
            h = self.router.headers
            xff = (
                getattr(h, "x_forwarded_for", "") or ""
            ).split(",")[0].strip()
            if xff:
                return xff
            return getattr(self.router, "client_ip", "") or ""
        except Exception:
            return ""

    @rx.event
    def attempt_login(self, form_data: dict):
        username = (form_data.get("username") or "").strip()
        password = form_data.get("password") or ""
        remember = form_data.get("remember") in ("on", "true", True)
        ip = self._client_ip()

        # Throttle brute-force attempts per username.
        allowed, retry = _login_check(username)
        if not allowed:
            mins = max(1, retry // 60)
            unit = "minute" if mins == 1 else "minutes"
            self.login_error = (
                f"Too many failed attempts. Try again in {mins} {unit}."
            )
            return

        user = chores_db.get_user_by_username(username)
        if not user or not user.get("password_hash"):
            _login_record_failure(username)
            chores_db.log_audit(
                None, None, "auth.login_fail", target=username,
                detail="unknown user", ip=ip,
            )
            self.login_error = "Invalid username or password."
            return
        if not chores_db.verify_password(password, user["password_hash"]):
            _login_record_failure(username)
            chores_db.log_audit(
                None, None, "auth.login_fail", target=username,
                detail="bad password", ip=ip,
            )
            self.login_error = "Invalid username or password."
            return
        _login_record_success(username)
        chores_db.log_audit(
            int(user["id"]), user["name"], "auth.login_success",
            target=username, detail=f"remember={remember}", ip=ip,
        )

        # Transparently upgrade legacy weak password hashes (e.g. the old
        # 200k-iteration PBKDF2 hashes) now that we know the plaintext.
        try:
            if chores_db.password_hash_needs_upgrade(user["password_hash"]):
                chores_db.update_password_hash(int(user["id"]), password)
        except Exception:
            pass

        self._apply(user)
        # ALWAYS issue a server-side session + set the cookie. Otherwise
        # the cookie is empty and image-route requests (which can't read
        # the in-memory Reflex state) fail auth with 401, producing the
        # broken-image-icon symptom on /inventory/capture etc.
        # "Remember me" controls session lifetime only — 30 days if ticked,
        # 12 hours if not. The browser still gets a max-age cookie either
        # way (Reflex's rx.Cookie max_age is a class-level constant), but
        # the server-side session enforces the shorter window.
        # 30 days if "remember me" is checked, 1 day otherwise. The cookie
        # max-age is fixed at 30 days; this just shortens the server-side
        # session window for non-remembered logins.
        token = chores_db.create_session(
            int(user["id"]), days=30 if remember else 1,
        )
        self.session_token = token
        self.login_error = ""
        return rx.redirect("/")

    @rx.event
    def attempt_setup(self, form_data: dict):
        chores_db.init_db()
        if chores_db.has_any_authed_users():
            self.setup_error = "Setup already complete. Please log in."
            return rx.redirect("/login")
        name = (form_data.get("name") or "").strip()
        username = (form_data.get("username") or "").strip()
        password = form_data.get("password") or ""
        password_confirm = form_data.get("password_confirm") or ""
        if not name:
            self.setup_error = "Name is required."
            return
        if not username:
            self.setup_error = "Username is required."
            return
        if len(password) < 8:
            self.setup_error = "Password must be at least 8 characters."
            return
        if password != password_confirm:
            self.setup_error = "Passwords don't match."
            return
        try:
            user_id = chores_db.create_first_admin(
                name=name, username=username, password=password
            )
        except Exception as exc:
            self.setup_error = _safe_error(exc, "Could not create the admin user.")
            return
        user = chores_db.get_user_by_id(user_id)
        if user:
            self._apply(user)
        self.setup_error = ""
        return rx.redirect("/")

    @rx.event
    def logout(self):
        token = self.session_token
        if token:
            try:
                chores_db.delete_session(token)
            except Exception:
                pass
        self.session_token = ""
        self._clear()
        return rx.redirect("/login")

    @rx.event
    def logout_everywhere(self):
        """Revoke every active session for this user (this device + any
        others). Useful if a cookie was leaked, a phone was lost, or you
        just want a clean slate."""
        uid = self.current_user_id
        name = self.current_user_name
        ip = self._client_ip()
        if uid:
            try:
                n = chores_db.delete_sessions_for_user(int(uid))
            except Exception:
                n = 0
            chores_db.log_audit(
                int(uid), name, "auth.logout_everywhere",
                detail=f"sessions_revoked={n}", ip=ip,
            )
        self.session_token = ""
        self._clear()
        return rx.redirect("/login")

    def _apply(self, user: dict):
        self.current_user_id = int(user["id"])
        self.current_user_name = user["name"]
        self.is_authed = True
        self.is_admin = bool(user.get("is_admin"))
        self.can_read_inventory = bool(user.get("can_read_inventory", 0))
        self.can_write_inventory = bool(user.get("can_write_inventory", 0))
        self.can_read_chores = bool(user.get("can_read_chores", 0))
        self.can_write_chores = bool(user.get("can_write_chores", 0))

    def _clear(self):
        self.current_user_id = 0
        self.current_user_name = ""
        self.is_authed = False
        self.is_admin = False
        self.can_read_inventory = False
        self.can_write_inventory = False
        self.can_read_chores = False
        self.can_write_chores = False


class CategoryStat(TypedDict):
    name: str
    count: int
    value: float


class RoomStat(TypedDict):
    name: str
    count: int
    value: float


class PersonTaskStat(TypedDict):
    name: str
    color: str
    open: int
    done: int


class HomeState(rx.State):
    """Home-page household briefing dashboard.

    Cards (in render order):
      - greeting: "Good morning/afternoon/evening, <name> · <time>"
      - agenda: tasks due today + appointments today, chronological
      - heads_up: food expiring + return windows + warranties soon
      - low_stock: items purchased recently but not re-added to groceries
      - activity: cross-module timeline of last ~12 events
      - prompt_of_day: time-of-day JARVIS prompt
    """

    # Greeting card
    greeting: str = ""
    greeting_time: str = ""

    # Agenda
    agenda: list[dict[str, Any]] = []

    # Heads-up (each list is one bucket; we show up to 3 in each)
    expiring_food: list[dict[str, Any]] = []
    returnable_soon: list[dict[str, Any]] = []
    warranty_soon: list[dict[str, Any]] = []

    # Low-stock prompts (recently bought, not re-added)
    low_stock: list[dict[str, Any]] = []

    # Cross-module activity feed
    activity: list[dict[str, Any]] = []

    # JARVIS prompt-of-the-day (legacy; no longer rendered on home)
    prompt_of_day: str = ""

    @rx.var
    def expiring_food_count(self) -> int:
        return len(self.expiring_food)

    @rx.var
    def returnable_soon_count(self) -> int:
        return len(self.returnable_soon)

    @rx.var
    def warranty_soon_count(self) -> int:
        return len(self.warranty_soon)

    @rx.var
    def heads_up_any(self) -> bool:
        return bool(self.expiring_food or self.returnable_soon or self.warranty_soon)

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir

        # Init every DB we touch so a fresh deployment doesn't 500.
        inv_db.init_db()
        chores_db.init_db()
        appt_db.init_db()
        groc_db.init_db()
        notes_db.init_db()

        auth = await self.get_state(AuthState)
        name = (auth.current_user_name or "").strip() or "there"
        # F7: per-module read-perm flags so we can clear cards the user
        # isn't authorized to see. Notes + groceries are universally
        # readable to authed users (no separate scope on AuthState).
        _can_inv = bool(auth.can_read_inventory)
        _can_chr = bool(auth.can_read_chores)

        # Tz-aware now() so the greeting respects the user's Settings ->
        # Appearance time zone without needing a systemd restart. Falls
        # back to naive datetime.now() if zoneinfo is unavailable.
        try:
            from zoneinfo import ZoneInfo
            from app_settings import db as _sdb
            now = datetime.now(ZoneInfo(_sdb.get_timezone()))
        except Exception:
            now = datetime.now()
        hour = now.hour
        if hour < 12:
            tod = "morning"
        elif hour < 18:
            tod = "afternoon"
        else:
            tod = "evening"
        self.greeting = f"Good {tod}, {name}"
        self.greeting_time = now.strftime("%a %b %d · %-I:%M %p") if os.name != "nt" else now.strftime("%a %b %d · %I:%M %p")

        # ---- Agenda: tasks due today + appointments today ----
        today_iso = now.strftime("%Y-%m-%d")
        agenda: list[dict[str, Any]] = []
        for t in chores_db.list_tasks(include_completed=False):
            if (t.get("due_date") or "") == today_iso:
                agenda.append({
                    "kind": "task",
                    "icon": "list-checks",
                    "title": t.get("title") or "",
                    "subtitle": (t.get("assignee_name") or "Unassigned"),
                    "sort_at": today_iso + " 00:00",
                    "href": "/chores/tasks",
                })
        for a in appt_db.list_appointments(upcoming_only=True):
            at = (a.get("appointment_at") or "")
            if at[:10] == today_iso:
                # Pretty time-of-day fragment
                time_str = ""
                try:
                    dt = datetime.fromisoformat(at.replace("T", " ")[:19])
                    time_str = dt.strftime("%-I:%M %p") if os.name != "nt" else dt.strftime("%I:%M %p")
                except (TypeError, ValueError):
                    time_str = at[11:16] if len(at) >= 16 else ""
                agenda.append({
                    "kind": "appointment",
                    "icon": "calendar",
                    "title": a.get("title") or "",
                    "subtitle": (time_str + (" · " + a.get("location") if a.get("location") else "")).strip(" ·"),
                    "sort_at": at,
                    "href": "/calendar",
                })
        agenda.sort(key=lambda r: r.get("sort_at") or "")
        self.agenda = agenda

        # ---- Heads-up ----
        def _pack_food(r: dict) -> dict:
            return {
                "name": r.get("name") or "",
                "detail": "expires " + (r.get("expires_at") or ""),
                "href": f"/inventory/item/{r.get('id')}" if r.get("id") else "/inventory/food",
            }

        def _pack_returnable(r: dict) -> dict:
            return {
                "name": r.get("name") or "",
                "detail": "return by " + (r.get("return_until") or ""),
                "href": f"/inventory/item/{r.get('id')}" if r.get("id") else "/inventory/browse",
            }

        def _pack_warranty(r: dict) -> dict:
            return {
                "name": r.get("name") or "",
                "detail": "warranty " + (r.get("warranty_until") or ""),
                "href": f"/inventory/item/{r.get('id')}" if r.get("id") else "/inventory/browse",
            }

        try:
            self.expiring_food = [_pack_food(r) for r in inv_db.items_expiring_within(7)[:3]]
        except Exception:
            self.expiring_food = []
        try:
            self.returnable_soon = [_pack_returnable(r) for r in inv_db.items_returnable_within(7)[:3]]
        except Exception:
            self.returnable_soon = []
        try:
            self.warranty_soon = [_pack_warranty(r) for r in inv_db.items_warranty_expiring_within(30)[:3]]
        except Exception:
            self.warranty_soon = []

        # ---- Low-stock prompts ----
        try:
            ls = groc_db.low_stock_candidates(days=14, limit=8)
        except Exception:
            ls = []
        self.low_stock = [
            {"name": r.get("name") or "", "purchased_at": r.get("purchased_at") or ""}
            for r in ls
        ]

        # ---- Recent activity ----
        events: list[dict[str, Any]] = []

        # Inventory events
        try:
            for r in inv_db.recent_item_events(limit=15):
                kind = r.get("kind") or ""
                item_name = r.get("item_name") or "an item"
                actor = (r.get("actor_name") or "").strip()
                actor_part = f"{actor} " if actor else ""
                if kind == "create":
                    text = f"{actor_part}added {item_name}".strip()
                elif kind == "loan":
                    text = f"{actor_part}loaned {item_name}".strip()
                elif kind == "return":
                    text = f"{actor_part}moved {item_name} back".strip()
                elif kind == "delete":
                    text = f"{actor_part}deleted {item_name}".strip()
                elif kind == "update":
                    text = f"{actor_part}updated {item_name}".strip()
                else:
                    text = f"{actor_part}{kind} on {item_name}".strip()
                item_id = r.get("item_id")
                href = (
                    f"/inventory/item/{int(item_id)}"
                    if item_id else "/inventory/browse"
                )
                events.append({
                    "icon": "package",
                    "ts": r.get("ts") or "",
                    "text": text,
                    "kind": "inventory",
                    "href": href,
                })
        except Exception:
            pass

        # Chore completions
        try:
            for r in chores_db.recent_completions(limit=15):
                actor = (r.get("assignee_name") or "").strip()
                actor_part = f"{actor} " if actor else ""
                title = r.get("title") or "a task"
                events.append({
                    "icon": "list-checks",
                    "ts": r.get("completed_at") or "",
                    "text": f"{actor_part}completed {title}".strip(),
                    "kind": "task",
                    "href": "/chores/tasks",
                })
        except Exception:
            pass

        # Notes
        try:
            for r in notes_db.recent_notes(limit=10):
                events.append({
                    "icon": "sticky-note",
                    "ts": r.get("created_at") or "",
                    "text": f"added note: {r.get('title') or '(untitled)'}",
                    "kind": "note",
                    "href": "/notes",
                })
        except Exception:
            pass

        # Grocery ticks
        try:
            for r in groc_db.recent_grocery_ticks(limit=10):
                events.append({
                    "icon": "shopping-cart",
                    "ts": r.get("purchased_at") or "",
                    "text": f"marked {r.get('name') or 'an item'} as bought",
                    "kind": "grocery",
                    "href": "/groceries",
                })
        except Exception:
            pass

        # Sort newest-first and trim to ~12
        def _ts_key(ev: dict[str, Any]) -> str:
            return ev.get("ts") or ""

        events.sort(key=_ts_key, reverse=True)
        trimmed: list[dict[str, Any]] = []
        for ev in events[:12]:
            ev["ts_rel"] = _relative_ts(ev.get("ts") or "")
            trimmed.append(ev)
        self.activity = trimmed

        # ---- Prompt of the day ----
        if tod == "morning":
            self.prompt_of_day = "Want me to recap your day?"
        elif tod == "afternoon":
            self.prompt_of_day = "Need a hand with errands or dinner?"
        else:
            self.prompt_of_day = "Want a quick wrap-up of today's loose ends?"

        # F7: scrub cards belonging to modules the user can't read. We
        # populate everything first (the queries are cheap and the
        # cross-module activity feed needs a unified view to sort by
        # timestamp), then filter at the end. Notes + groceries have
        # no separate read-perm today, so they pass through.
        if not _can_inv:
            self.expiring_food = []
            self.returnable_soon = []
            self.warranty_soon = []
            self.activity = [
                e for e in self.activity
                if e.get("kind") not in ("inventory", "item_history", "item")
            ]
        if not _can_chr:
            self.agenda = [
                a for a in self.agenda
                if a.get("kind") not in ("task", "appointment")
            ]
            self.activity = [
                e for e in self.activity
                if e.get("kind") not in ("task", "appointment", "completion", "chore")
            ]


def _relative_ts(ts: str) -> str:
    """Convert an ISO-ish timestamp into a short '2h ago' style string.
    Returns '' on parse failure."""
    if not ts:
        return ""
    raw = ts.replace("T", " ")[:19]
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        try:
            dt = datetime.strptime(raw[:10], "%Y-%m-%d")
        except (TypeError, ValueError):
            return ""
    delta = datetime.now() - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        secs = 0
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    days = hrs // 24
    if days < 7:
        return f"{days}d ago"
    return dt.strftime("%b %d")



class InventorySearchState(rx.State):
    query: str = ""
    results: list[ItemRow] = []
    view_mode: str = "list"  # "list" | "grid" | "compact"

    @rx.event
    def set_view_mode(self, value: str):
        self.view_mode = value

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self, read="inventory")
        if redir is not None:
            return redir

    @rx.event
    def set_query(self, value: str):
        self.query = value
        self._refresh()

    @rx.event
    async def delete_item(self, item_id: int):
        # Optimistic: drop the row from self.results, yield so the
        # client repaints, then soft-delete in a worker thread.
        snapshot = list(self.results)
        item = next(
            (i for i in self.results if int(i["id"]) == int(item_id)), None
        )
        self.results = [
            i for i in self.results if int(i["id"]) != int(item_id)
        ]
        yield
        try:
            db_item = await asyncio.to_thread(inv_db.get_item, int(item_id))
            await asyncio.to_thread(inv_db.delete_item, int(item_id))
        except Exception:
            self.results = snapshot
            yield rx.toast.error("Couldn't delete item. Try again.")
            return
        if db_item:
            undo = await self.get_state(UndoState)
            undo.arm(
                "inventory", {"id": int(item_id)},
                f"Deleted {db_item.get('name') or 'item'}.",
            )

    def _refresh(self):
        q = self.query.strip()
        if not q:
            self.results = []
            return
        raw = inv_db.search_items(q, limit=50)
        self.results = [_enrich_item_row(r) for r in raw]


# ---- Inventory Browse --------------------------------------------------------
_ALL_ROOMS = "All rooms"
_ALL_CATS = "All categories"
_SALE_ALL = "All items"
_SALE_YES = "For sale only"
_SALE_NO = "Not for sale only"

_SORT_OPTIONS = [
    "Most recent first",
    "A → Z",
    "Z → A",
    "Highest value",
    "Lowest value",
    "Highest quantity",
    "Lowest quantity",
]


def _apply_sort(items: list[dict], sort_by: str) -> list[dict]:
    if sort_by == "A → Z":
        return sorted(items, key=lambda it: (it.get("name") or "").lower())
    if sort_by == "Z → A":
        return sorted(
            items, key=lambda it: (it.get("name") or "").lower(), reverse=True
        )
    if sort_by == "Highest value":
        return sorted(
            items,
            key=lambda it: float(it.get("estimated_value") or 0),
            reverse=True,
        )
    if sort_by == "Lowest value":
        return sorted(
            items, key=lambda it: float(it.get("estimated_value") or 0)
        )
    if sort_by == "Highest quantity":
        return sorted(
            items, key=lambda it: int(it.get("quantity") or 0), reverse=True
        )
    if sort_by == "Lowest quantity":
        return sorted(items, key=lambda it: int(it.get("quantity") or 0))
    # "Most recent first" (default)
    return sorted(
        items, key=lambda it: it.get("created_at") or "", reverse=True
    )


class InventoryBrowseState(rx.State):
    room: str = _ALL_ROOMS
    sort_by: str = "Most recent first"
    category_filter: str = _ALL_CATS
    for_sale_filter: str = _SALE_ALL
    view_mode: str = "list"  # "list" | "grid" | "compact"
    items: list[ItemRow] = []
    room_summary: list[RoomSummary] = []
    rooms: list[str] = []

    @rx.event
    def set_view_mode(self, value: str):
        self.view_mode = value

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self, read="inventory")
        if redir is not None:
            return redir
        inv_db.init_db()
        self.rooms = sorted(
            inv_db.list_room_names() or list(config.ROOMS), key=str.lower
        )
        self.room_summary = [
            {"room": r, "count": n}
            for r, n in inv_db.all_rooms_with_counts()
            if n > 0
        ]
        self._refresh()

    @rx.event
    def set_room(self, value: str):
        self.room = value
        self._refresh()

    @rx.event
    def set_sort(self, value: str):
        self.sort_by = value
        self._refresh()

    @rx.event
    def set_category(self, value: str):
        self.category_filter = value
        self._refresh()

    @rx.event
    def set_for_sale(self, value: str):
        self.for_sale_filter = value
        self._refresh()

    @rx.event
    async def delete_item(self, item_id: int):
        if not await _require_write(self, "inventory"):
            return
        # Optimistic: drop the row from self.items, yield, soft-delete in DB
        # off-thread. Roll back on failure.
        snapshot = list(self.items)
        item = next(
            (i for i in self.items if int(i["id"]) == int(item_id)), None
        )
        self.items = [
            i for i in self.items if int(i["id"]) != int(item_id)
        ]
        yield
        try:
            db_item = await asyncio.to_thread(inv_db.get_item, int(item_id))
            await asyncio.to_thread(inv_db.delete_item, int(item_id))
        except Exception:
            self.items = snapshot
            yield rx.toast.error("Couldn't delete item. Try again.")
            return
        # Refresh to keep room counts + filters consistent.
        self._refresh()
        if db_item:
            undo = await self.get_state(UndoState)
            undo.arm(
                "inventory", {"id": int(item_id)},
                f"Deleted {db_item.get('name') or 'item'}.",
            )

    @rx.var
    def room_options(self) -> list[str]:
        return [_ALL_ROOMS] + self.rooms

    @rx.var
    def category_options(self) -> list[str]:
        return [_ALL_CATS] + config.CATEGORIES

    @rx.var
    def for_sale_options(self) -> list[str]:
        return [_SALE_ALL, _SALE_YES, _SALE_NO]

    @rx.var
    def sort_options(self) -> list[str]:
        return _SORT_OPTIONS

    def _refresh(self):
        items = (
            inv_db.all_items()
            if self.room == _ALL_ROOMS
            else inv_db.items_in_room(self.room)
        )

        if self.category_filter and self.category_filter != _ALL_CATS:
            items = [
                i for i in items
                if (i.get("category") or "") == self.category_filter
            ]

        if self.for_sale_filter == _SALE_YES:
            items = [i for i in items if i.get("for_sale")]
        elif self.for_sale_filter == _SALE_NO:
            items = [i for i in items if not i.get("for_sale")]

        items = _apply_sort(items, self.sort_by)
        self.items = [_enrich_item_row(it) for it in items]

        # Also rebuild the per-room count strip so deleting an item
        # immediately updates the stat cards at the top of the page.
        # Skip rooms that have dropped to zero — they shouldn't keep
        # taking up a chip after their last item is removed.
        self.room_summary = [
            {"room": r, "count": n}
            for r, n in inv_db.all_rooms_with_counts()
            if n > 0
        ]


# ---- Inventory For-Sale ------------------------------------------------------
class InventoryForSaleState(rx.State):
    """Items currently marked `for_sale = 1`."""

    items: list[ItemRow] = []
    sort_by: str = "Most recent first"
    view_mode: str = "list"
    total_count: int = 0
    total_value_display: str = "$0.00"

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self, read="inventory")
        if redir is not None:
            return redir
        inv_db.init_db()
        self._refresh()

    @rx.event
    def set_sort(self, value: str):
        self.sort_by = value
        self._refresh()

    @rx.event
    def set_view_mode(self, value: str):
        self.view_mode = value

    @rx.event
    async def delete_item(self, item_id: int):
        if not await _require_write(self, "inventory"):
            return
        snapshot = list(self.items)
        self.items = [
            i for i in self.items if int(i["id"]) != int(item_id)
        ]
        self.total_count = max(0, self.total_count - 1)
        yield
        try:
            db_item = await asyncio.to_thread(inv_db.get_item, int(item_id))
            await asyncio.to_thread(inv_db.delete_item, int(item_id))
        except Exception:
            self.items = snapshot
            self.total_count = len(snapshot)
            yield rx.toast.error("Couldn't delete item. Try again.")
            return
        if db_item:
            undo = await self.get_state(UndoState)
            undo.arm(
                "inventory", {"id": int(item_id)},
                f"Deleted {db_item.get('name') or 'item'}.",
            )

    @rx.var
    def sort_options(self) -> list[str]:
        return _SORT_OPTIONS

    def _refresh(self):
        items = inv_db.for_sale_items()
        items = _apply_sort(items, self.sort_by)
        self.total_count = len(items)
        total_value = sum(float(i.get("estimated_value") or 0) for i in items)
        self.total_value_display = f"${total_value:,.2f}"
        self.items = [_enrich_item_row(it) for it in items]


# ---- Inventory Food ----------------------------------------------------------
class InventoryFoodState(rx.State):
    """Items whose category is food-related (pantry, spices)."""

    items: list[ItemRow] = []
    sort_by: str = "Most recent first"
    view_mode: str = "list"
    total_count: int = 0

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self, read="inventory")
        if redir is not None:
            return redir
        inv_db.init_db()
        self._refresh()

    @rx.event
    def set_sort(self, value: str):
        self.sort_by = value
        self._refresh()

    @rx.event
    def set_view_mode(self, value: str):
        self.view_mode = value

    @rx.event
    async def delete_item(self, item_id: int):
        if not await _require_write(self, "inventory"):
            return
        snapshot = list(self.items)
        self.items = [
            i for i in self.items if int(i["id"]) != int(item_id)
        ]
        self.total_count = max(0, self.total_count - 1)
        yield
        try:
            db_item = await asyncio.to_thread(inv_db.get_item, int(item_id))
            await asyncio.to_thread(inv_db.delete_item, int(item_id))
        except Exception:
            self.items = snapshot
            self.total_count = len(snapshot)
            yield rx.toast.error("Couldn't delete item. Try again.")
            return
        if db_item:
            undo = await self.get_state(UndoState)
            undo.arm(
                "inventory", {"id": int(item_id)},
                f"Deleted {db_item.get('name') or 'item'}.",
            )

    @rx.var
    def sort_options(self) -> list[str]:
        return _SORT_OPTIONS

    def _refresh(self):
        items = inv_db.food_items()
        items = _apply_sort(items, self.sort_by)
        self.total_count = len(items)
        self.items = [_enrich_item_row(it) for it in items]


# ---- Inventory Trash ---------------------------------------------------------
class InventoryTrashState(rx.State):
    """Soft-deleted inventory items, with restore + permanent-delete actions."""

    items: list[ItemRow] = []

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self, read="inventory")
        if redir is not None:
            return redir
        inv_db.init_db()
        self._refresh()

    @rx.event
    async def restore(self, item_id: int):
        if not await _require_write(self, "inventory"):
            return
        inv_db.restore_item(int(item_id))
        self._refresh()

    @rx.event
    async def purge(self, item_id: int):
        if not await _require_write(self, "inventory"):
            return
        inv_db.purge_item(int(item_id))
        self._refresh()

    @rx.event
    async def empty_trash(self):
        if not await _require_write(self, "inventory"):
            return
        inv_db.purge_all_deleted()
        self._refresh()

    def _refresh(self):
        raw = inv_db.list_deleted_items()
        self.items = [_enrich_item_row(it) for it in raw]


# ---- Inventory Capture -------------------------------------------------------
class InventoryCaptureState(rx.State):
    # Defaults to a generic "default" bucket; user can change before upload.
    room: str = "default"
    rooms: list[str] = []
    uploading: bool = False
    recognizing: bool = False
    # User-facing progress reporting during recognition.
    status: str = ""
    progress: int = 0
    photo_url: str = ""
    photo_path: str = ""
    items: list[CapturedItem] = []
    error: str = ""
    saved_message: str = ""
    # "objects" = normal photo of physical items (LLM + OWL detector)
    # "receipt" = photo of a paper receipt (LLM extracts line items only)
    mode: str = "objects"
    # Receipt-mode grocery reconciliation. After a receipt scan, any
    # auto-ticked grocery rows land here so the UI can show a green callout
    # ("Auto-checked N items from your grocery list").
    grocery_matches: list[dict[str, str]] = []  # [{id, name}, ...]
    receipt_store: str = ""
    receipt_date: str = ""
    receipt_total: float = 0.0

    @rx.event
    def set_mode(self, value: str):
        self.mode = value if value in ("objects", "receipt") else "objects"

    @rx.var
    def in_progress(self) -> bool:
        return self.uploading or self.recognizing

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self, read="inventory")
        if redir is not None:
            yield redir
            return
        inv_db.init_db()
        # Alphabetical order, with a "default" bucket always available and
        # pre-selected so uploads work without picking a room first.
        names = inv_db.list_room_names() or list(config.ROOMS)
        if "default" not in (n.lower() for n in names):
            names = list(names) + ["default"]
        self.rooms = sorted(names, key=str.lower)
        if not self.room or self.room not in self.rooms:
            self.room = "default"

        # After /api/capture-upload posts a photo, the client reloads
        # the page with ?recent=<photo_id> so we can rehydrate the
        # summary list with what just got saved. Bounded to integers
        # we already control via the items table.
        try:
            recent = self.router.page.params.get("recent")
        except Exception:
            recent = None
        if recent:
            try:
                pid = int(recent)
            except (TypeError, ValueError):
                pid = 0
            if pid > 0:
                # Set photo_url/photo_path so has_photo is True and the
                # summary block (photo + per-item rows with thumbnails +
                # qty +/- + trash) actually renders. Without this the
                # user only sees the "Saved N item(s)" toast and not the
                # full editable summary they had on the in-process flow.
                try:
                    photo_path = inv_db.photo_path_by_id(pid)
                except Exception:
                    photo_path = ""
                if photo_path:
                    self.photo_path = photo_path
                    self.photo_url = _photo_url(photo_path)
                try:
                    rows = inv_db.items_for_photo(pid)
                except Exception:
                    rows = []
                self.items = [
                    {
                        "idx": i,
                        "item_id": int(r["id"]),
                        "name": r.get("name", ""),
                        "category": r.get("category", "") or "",
                        "quantity": int(r.get("quantity") or 1),
                        "detector_count": int(r.get("detector_count") or 0),
                        "boxes": r.get("boxes") or [],
                        "keep": True,
                        "for_sale": False,
                        "estimated_value": float(
                            r.get("estimated_value") or 0.0
                        ),
                    }
                    for i, r in enumerate(rows)
                ]
                if self.items:
                    self.saved_message = (
                        f"Saved {len(self.items)} item(s)."
                    )
                # Strip ?recent= so a manual refresh does not re-trigger
                # the rehydrate path. The user expects refresh to drop
                # them back to a clean Add-item page.
                yield rx.call_script(
                    "try { const u = new URL(window.location.href); "
                    "u.searchParams.delete('recent'); "
                    "window.history.replaceState({}, '', u.toString()); } "
                    "catch(e){}"
                )

        # PWA share-target handoff: if the browser carries the cookie set
        # by /share-target, ingest that file as if dropped on the upload
        # zone. Chained inline so it doesn't break codegen as a separate
        # on_load handler.
        async for ev in self._pickup_shared_photo():
            yield ev

    async def _pickup_shared_photo(self):
        """Internal async generator: yield Reflex events to ingest a
        shared-target photo (set by /share-target's cookie). No-op if
        no cookie is present. NOT an @rx.event — invoked from on_load."""
        import sys

        try:
            raw_cookie = getattr(self.router.headers, "cookie", "") or ""
        except Exception:
            raw_cookie = ""
        path: str = ""
        for part in raw_cookie.split(";"):
            part = part.strip()
            if part.startswith("gyst_shared_photo="):
                path = part.split("=", 1)[1]
                break
        if not path:
            return
        # SECURITY: validate the cookie-supplied path lives under
        # config.PHOTOS_DIR/shared/. Without this check, a malicious
        # cookie value (e.g. /etc/passwd or ../../etc/secrets) would be
        # read by p.read_bytes() below and exfiltrated into the LLM
        # recognition pipeline. See CWE-22 and the doc on
        # _is_safe_shared_photo_path.
        p = _is_safe_shared_photo_path(path)
        if p is None:
            yield rx.call_script(
                "document.cookie = 'gyst_shared_photo=; Max-Age=0; Path=/';"
            )
            return
        if not p.exists() or not p.is_file():
            yield rx.call_script(
                "document.cookie = 'gyst_shared_photo=; Max-Age=0; Path=/';"
            )
            return
        try:
            data = p.read_bytes()
        except Exception as exc:
            print(f"[capture/shared] read failed: {exc!r}", file=sys.stderr)
            yield rx.call_script(
                "document.cookie = 'gyst_shared_photo=; Max-Age=0; Path=/';"
            )
            return

        class _SharedUpload:
            def __init__(self, name: str, payload: bytes):
                self.filename = name
                self._payload = payload
                self.content_type = "image/jpeg"

            async def read(self) -> bytes:
                return self._payload

        yield rx.call_script(
            "document.cookie = 'gyst_shared_photo=; Max-Age=0; Path=/';"
        )
        async for ev in self.handle_upload([_SharedUpload(p.name, data)]):
            yield ev
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass

    @rx.var
    def room_options(self) -> list[str]:
        return self.rooms

    @rx.var
    def category_options(self) -> list[str]:
        return config.CATEGORIES

    @rx.var
    def has_photo(self) -> bool:
        return bool(self.photo_url)

    @rx.event
    def set_room(self, value: str):
        self.room = value

    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        import sys
        import traceback

        print(
            f"[capture] handle_upload start; "
            f"files={len(files) if files else 0}",
            file=sys.stderr,
        )

        if not files:
            print("[capture] no files in payload, aborting", file=sys.stderr)
            return

        if not self.room:
            self.error = "Please pick a room before uploading a photo."
            return
        # Reject anything not on the server's room allow-list — `self.room`
        # could otherwise carry crafted path fragments into the on-disk
        # filename via a tampered state mutation.
        if self.room not in self.rooms:
            self.error = "Invalid room selection."
            return

        self.error = ""
        self.saved_message = ""
        self.items = []
        self.photo_url = ""
        self.uploading = True
        self.status = "Saving photo…"
        self.progress = 10
        yield

        try:
            f = files[0]
            data = await f.read()
            print(
                f"[capture] read {len(data)} bytes from "
                f"{getattr(f, 'filename', '?')}",
                file=sys.stderr,
            )
            config.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
            # Unguessable filename so the (now-auth-gated) photo endpoint
            # also can't be enumerated.
            import secrets as _sec

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            token = _sec.token_hex(8)
            out_path = config.PHOTOS_DIR / f"{ts}_{token}.jpg"
            await asyncio.to_thread(_save_oriented_jpeg, data, out_path)
            self.photo_path = str(out_path)
            self.photo_url = _photo_url(self.photo_path)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            self.error = _safe_error(exc, "Upload failed. Try again or pick a smaller photo.")
            self.uploading = False
            self.status = ""
            self.progress = 0
            yield
            return

        self.uploading = False
        self.recognizing = True
        if self.mode == "receipt":
            self.status = "Reading receipt…"
        else:
            self.status = "Identifying items with Claude…"
        self.progress = 30
        yield

        # ---- Receipt-mode fork ----------------------------------------
        if self.mode == "receipt":
            try:
                receipt = await asyncio.to_thread(
                    recognize.identify_receipt, Path(self.photo_path)
                )
                line_items = receipt.get("items") or []
                print(
                    f"[capture/receipt] {len(line_items)} line item(s) extracted"
                    f"; store={receipt.get('store')!r}"
                    f" date={receipt.get('date')!r}",
                    file=sys.stderr,
                )
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                self.error = _friendly_llm_error(exc, action="receipt OCR")
                self.recognizing = False
                self.status = ""
                self.progress = 0
                return
            if not line_items:
                self.recognizing = False
                self.status = "No line items detected on this image."
                self.progress = 100
                return
            # Compute a default 30-day return window from purchase date.
            # TODO: per-store return-window configurability (e.g. Costco
            # has effectively-unlimited, Best Buy is 14 days).
            purchase_date = receipt.get("date") or date.today().isoformat()
            return_until = None
            try:
                pd = datetime.strptime(purchase_date, "%Y-%m-%d").date()
                return_until = (pd + timedelta(days=30)).isoformat()
            except (TypeError, ValueError):
                return_until = None
            self.receipt_store = receipt.get("store") or ""
            self.receipt_date = purchase_date
            self.receipt_total = float(receipt.get("total") or 0.0)
            try:
                photo_id = await asyncio.to_thread(
                    inv_db.save_photo, self.photo_path, self.room
                )
                candidates = [
                    {
                        "name": li["name"],
                        "category": "pantry / food",
                        "quantity": int(li.get("quantity") or 1),
                        "detector_count": 0,
                        "boxes": [],
                        "for_sale": False,
                        "estimated_value": li.get("price"),
                    }
                    for li in line_items
                ]
                new_ids = await asyncio.to_thread(
                    inv_db.save_items, photo_id, candidates,
                )
                # Persist purchase metadata on each saved row.
                store = self.receipt_store or None
                for new_id, li in zip(new_ids, line_items):
                    try:
                        inv_db.set_purchase(
                            int(new_id),
                            purchase_date=purchase_date,
                            price=li.get("price"),
                            store=store,
                            return_until=return_until,
                        )
                    except Exception:
                        pass
            except Exception as exc:
                self.error = _safe_error(
                    exc, "Could not save receipt items."
                )
                self.recognizing = False
                self.status = ""
                self.progress = 0
                return
            self.items = [
                {
                    "idx": i,
                    "item_id": int(new_ids[i]) if i < len(new_ids) else 0,
                    "name": c["name"],
                    "category": c["category"],
                    "quantity": int(c["quantity"]),
                    "detector_count": 0,
                    "boxes": [],
                    "keep": True,
                    "for_sale": False,
                    "estimated_value": float(c["estimated_value"] or 0.0),
                }
                for i, c in enumerate(candidates)
            ]
            # ---- Grocery-list reconciliation ----
            # Cross-check each receipt line against open (unchecked) grocery
            # items; auto-tick any match. Names are normalized (lowercase,
            # punctuation stripped, common suffixes like 'lb'/'oz' trimmed)
            # then substring-tested both directions.
            try:
                self.grocery_matches = self._reconcile_groceries(
                    [c["name"] for c in candidates]
                )
            except Exception as exc:
                import sys, traceback
                traceback.print_exc(file=sys.stderr)
                self.grocery_matches = []
            # Arm an undo so the user can revert all auto-ticks.
            if self.grocery_matches:
                undo = await self.get_state(UndoState)
                undo.arm(
                    "grocery_recon",
                    {"ids": [int(m["id"]) for m in self.grocery_matches]},
                    f"Auto-checked {len(self.grocery_matches)} grocery item(s).",
                )
            self.saved_message = (
                f"Saved {len(self.items)} item(s) from receipt to "
                f"{self.room}."
            )
            self.recognizing = False
            self.status = (
                f"Done — {len(self.items)} line item(s) added."
            )
            self.progress = 100
            return

        try:
            identified = await asyncio.to_thread(
                recognize.identify_items, Path(self.photo_path)
            )
            print(
                f"[capture] LLM identified {len(identified)} types",
                file=sys.stderr,
            )
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            self.error = _friendly_llm_error(exc, action="identification")
            self.recognizing = False
            self.status = ""
            self.progress = 0
            return

        if not identified:
            self.recognizing = False
            self.status = "Nothing recognizable in this photo."
            self.progress = 100
            return

        # ---- Bookshelf shortcut --------------------------------------
        # If the LLM tagged this as a books-heavy photo, skip the OWL
        # detector and per-crop title pass and instead ask the LLM to
        # enumerate every title in one shot. Far more accurate for shelves
        # because the model gets full spatial + textual context.
        book_signal = any(
            "book" in (it.name or "").lower()
            or "novel" in (it.name or "").lower()
            for it in identified
        )
        bookshelf_mode = book_signal and (
            len(identified) == 1
            or sum((it.llm_quantity or 1) for it in identified) >= 3
        )
        if bookshelf_mode:
            self.status = "Reading every visible title…"
            self.progress = 60
            yield
            try:
                shelf = await asyncio.to_thread(
                    recognize.extract_book_titles_from_shelf,
                    Path(self.photo_path),
                )
                print(
                    f"[capture/shelf] {len(shelf)} title(s) extracted",
                    file=sys.stderr,
                )
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                self.error = _friendly_llm_error(
                    exc, action="bookshelf reading",
                )
                self.recognizing = False
                self.status = ""
                self.progress = 0
                return

            if not shelf:
                # Fall through to the normal pipeline if the shelf prompt
                # returned nothing — never strand the user.
                book_signal = False
                bookshelf_mode = False
            else:
                try:
                    photo_id = await asyncio.to_thread(
                        inv_db.save_photo, self.photo_path, self.room,
                    )
                    candidates = [
                        {
                            "name": s["name"],
                            "category": "book",
                            "quantity": int(s.get("quantity") or 1),
                            "detector_count": 0,
                            "boxes": [],
                            "for_sale": False,
                            "estimated_value": None,
                        }
                        for s in shelf
                    ]
                    new_ids = await asyncio.to_thread(
                        inv_db.save_items, photo_id, candidates,
                    )
                except Exception as exc:
                    self.error = _safe_error(
                        exc, "Could not save the books from the shelf.",
                    )
                    self.recognizing = False
                    self.status = ""
                    self.progress = 0
                    return

                self.items = [
                    {
                        "idx": i,
                        "item_id": int(new_ids[i]) if i < len(new_ids) else 0,
                        "name": c["name"],
                        "category": c["category"],
                        "quantity": int(c["quantity"]),
                        "detector_count": 0,
                        "boxes": [],
                        "keep": True,
                        "for_sale": False,
                        "estimated_value": 0.0,
                    }
                    for i, c in enumerate(candidates)
                ]
                self.saved_message = (
                    f"Saved {len(self.items)} book(s) from the shelf to "
                    f"{self.room}."
                )
                self.recognizing = False
                self.status = (
                    f"Done — {len(self.items)} book(s) identified."
                )
                self.progress = 100
                return

        labels = [it.name for it in identified]
        self.status = (
            f"Counting instances of {len(labels)} item type(s)…"
        )
        self.progress = 55
        yield

        try:
            counts, boxes_per_label = await asyncio.to_thread(
                recognize.count_items, Path(self.photo_path), labels
            )
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            self.error = _friendly_llm_error(exc, action="counting")
            self.recognizing = False
            self.status = ""
            self.progress = 0
            return

        if recognize.has_text_items(identified):
            self.status = "Reading titles on books / DVDs / labels…"
            self.progress = 80
            yield

        try:
            recognized = await asyncio.to_thread(
                recognize.refine_text_items,
                Path(self.photo_path),
                identified,
                counts,
                boxes_per_label,
            )
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            self.error = _friendly_llm_error(exc, action="title reading")
            self.recognizing = False
            self.status = ""
            self.progress = 0
            return

        # Build the candidate rows from the recognizer output.
        candidates = [
            {
                "name": r.name,
                "category": r.category,
                "quantity": (
                    r.detector_count
                    if r.detector_count and r.detector_count > 0
                    else r.llm_quantity
                ),
                "detector_count": r.detector_count or 0,
                "boxes": r.boxes or [],
                "for_sale": False,
                "estimated_value": float(r.estimated_value or 0.0),
            }
            for r in recognized
        ]

        # Auto-commit everything to inventory. The user no longer has to tap
        # 'Save' — the summary below the photo is the receipt of what got
        # added, with a delete button per row in case the recognizer mis-
        # identified something.
        try:
            photo_id = await asyncio.to_thread(
                inv_db.save_photo, self.photo_path, self.room
            )
            new_ids = await asyncio.to_thread(
                inv_db.save_items, photo_id, candidates,
            )
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            self.error = _safe_error(exc, "Could not save items to inventory.")
            self.recognizing = False
            self.status = ""
            self.progress = 0
            return

        self.items = [
            {
                "idx": i,
                "item_id": int(new_ids[i]) if i < len(new_ids) else 0,
                "name": c["name"],
                "category": c["category"],
                "quantity": int(c["quantity"]),
                "detector_count": c["detector_count"],
                "boxes": c["boxes"],
                "keep": True,
                "for_sale": False,
                "estimated_value": float(c["estimated_value"]),
            }
            for i, c in enumerate(candidates)
        ]
        self.saved_message = (
            f"Saved {len(self.items)} item(s) to {self.room}. "
            "Delete any that look wrong below."
        )
        self.recognizing = False
        self.status = f"Done — {len(self.items)} item(s) added."
        self.progress = 100

    @rx.event
    def undo_grocery_match(self, gid: int):
        """Revert a single auto-tick from the receipt summary callout."""
        try:
            groc_db.set_purchased(int(gid), False)
        except Exception:
            return
        self.grocery_matches = [
            m for m in self.grocery_matches if int(m.get("id") or 0) != int(gid)
        ]

    @staticmethod
    def _normalize_grocery_name(name: str) -> str:
        """Lowercase, strip punctuation, drop trailing unit/qty noise so
        'BNNAS 2.3 LB' matches 'bananas' from the grocery list."""
        import re as _re

        s = (name or "").lower().strip()
        s = _re.sub(r"[^a-z0-9\s]", " ", s)
        # Trim common unit / pack words.
        s = _re.sub(
            r"\b("
            r"lb|lbs|oz|ozs|kg|g|gal|gallon|qt|pt|ct|pk|pack|"
            r"each|ea|dozen|doz|count|pcs|piece|pieces"
            r")\b",
            " ", s,
        )
        s = _re.sub(r"\b\d+(\.\d+)?\b", " ", s)
        return _re.sub(r"\s+", " ", s).strip()

    def _reconcile_groceries(self, receipt_names: list[str]) -> list[GroceryMatchRow]:
        """Substring-match each receipt line against open grocery items.
        Auto-tick matches via groc_db.set_purchased. Returns the list of
        matched grocery rows (for the undo arming + UI callout)."""
        norm_lines = [
            (raw, self._normalize_grocery_name(raw)) for raw in receipt_names
        ]
        norm_lines = [(r, n) for r, n in norm_lines if n]
        if not norm_lines:
            return []
        groc_db.init_db()
        opens = groc_db.list_groceries(include_purchased=False)
        matches: list[dict] = []
        for g in opens:
            gname = self._normalize_grocery_name(g.get("name") or "")
            if not gname:
                continue
            for _raw, nline in norm_lines:
                if gname in nline or nline in gname:
                    try:
                        groc_db.set_purchased(int(g["id"]), True)
                    except Exception:
                        continue
                    matches.append({"id": str(g["id"]), "name": str(g["name"])})
                    break
        return matches


    @rx.event
    async def adjust_saved_quantity(self, idx: int, delta: int):
        """Bump a saved item's quantity by +1 / -1, persisting to the DB
        and updating the summary row. If it would drop to 0, treat it as
        a delete."""
        if not (0 <= idx < len(self.items)):
            return
        if not await _require_write(self, "inventory"):
            return
        item = self.items[idx]
        new_q = int(item.get("quantity") or 0) + int(delta)
        if new_q <= 0:
            return await self.delete_saved_item(idx)
        item_id = int(item.get("item_id") or 0)
        if item_id:
            try:
                inv_db.update_item(
                    item_id,
                    name=item.get("name") or "",
                    quantity=new_q,
                    category=item.get("category") or "other",
                )
            except Exception:
                pass
        self.items[idx] = {**item, "quantity": new_q}

    @rx.event
    async def add_barcode_item(self, name: str, upc: str = ""):
        """Insert a single item directly into inventory — used by the
        barcode scanner after a successful UPC → product lookup. Bypasses
        the LLM/OWL pipeline entirely; we already know what it is."""
        if not name or not name.strip():
            return
        if not await _require_write(self, "inventory"):
            return
        if not self.room or self.room not in self.rooms:
            self.error = "Pick a room before scanning a barcode."
            return
        try:
            # Reuse the same photo if the user already captured one this
            # session; otherwise stamp a synthetic photo row pointing at
            # a tiny placeholder path. The placeholder never resolves to
            # a file but the inventory schema requires a photo_id.
            if self.photo_path:
                photo_id = inv_db.save_photo(self.photo_path, self.room)
            else:
                photo_id = inv_db.save_photo(
                    f"barcode://{upc or 'manual'}", self.room,
                )
            new_ids = inv_db.save_items(
                photo_id,
                [{
                    "name": name.strip(),
                    "category": "pantry / food",
                    "quantity": 1,
                    "detector_count": 0,
                    "boxes": [],
                    "for_sale": False,
                    "estimated_value": None,
                }],
            )
        except Exception as exc:
            self.error = _safe_error(exc, "Could not save barcode item.")
            return
        new_id = int(new_ids[0]) if new_ids else 0
        new_idx = len(self.items)
        self.items = self.items + [{
            "idx": new_idx,
            "item_id": new_id,
            "name": name.strip(),
            "category": "pantry / food",
            "quantity": 1,
            "detector_count": 0,
            "boxes": [],
            "keep": True,
            "for_sale": False,
            "estimated_value": 0.0,
        }]
        self.saved_message = f"Added {name.strip()} (barcode)."

    @rx.event
    async def delete_saved_item(self, idx: int):
        """Soft-delete an item that was just auto-added, and drop it from
        the post-capture summary list."""
        if not (0 <= idx < len(self.items)):
            return
        if not await _require_write(self, "inventory"):
            return
        item = self.items[idx]
        item_id = int(item.get("item_id") or 0)
        snapshot_name = item.get("name") or ""
        if item_id:
            try:
                inv_db.delete_item(item_id)
            except Exception:
                pass
        self.items = [it for j, it in enumerate(self.items) if j != idx]
        # Re-number idx on the surviving rows so the next delete still
        # has a valid offset. Without this, deleting from the middle
        # leaves later items with stale idx values that fail the
        # `0 <= idx < len(self.items)` bounds check.
        for new_idx, it in enumerate(self.items):
            it["idx"] = new_idx
        if item_id:
            undo = await self.get_state(UndoState)
            undo.arm(
                "inventory", {"id": int(item_id)},
                f"Removed {snapshot_name or 'item'}.",
            )
        # Refresh the saved-message counter so it reflects the new total.
        if self.items:
            self.saved_message = (
                f"Saved {len(self.items)} item(s) to {self.room}. "
                "Delete any that look wrong below."
            )
        else:
            # Last item removed: drop the photo preview too so the page
            # returns to a clean slate. Otherwise the orphaned thumbnail
            # sits at the top with nothing under it.
            self.photo_url = ""
            self.photo_path = ""
            self.saved_message = (
                f"All items removed. Take another photo to add more."
            )

    @rx.event
    def save_to_inventory(self):
        kept = [it for it in self.items if it["keep"] and it["name"].strip()]
        if not kept:
            self.error = "Nothing to save — all rows unchecked or empty."
            return
        photo_id = inv_db.save_photo(self.photo_path, self.room)
        inv_db.save_items(
            photo_id,
            [
                {
                    "name": it["name"].strip(),
                    "category": it["category"],
                    "quantity": int(it["quantity"]),
                    "detector_count": it["detector_count"],
                    "boxes": it["boxes"],
                    "for_sale": bool(it.get("for_sale")),
                    "estimated_value": (
                        float(it["estimated_value"])
                        if it.get("estimated_value")
                        else None
                    ),
                }
                for it in kept
            ],
        )
        self.saved_message = f"Saved {len(kept)} item(s) to {self.room}."
        self.photo_url = ""
        self.photo_path = ""
        self.items = []
        self.error = ""


# ---- Chores Tasks ------------------------------------------------------------
class ChoresTasksState(rx.State):
    filter_value: str = "All open"
    tasks: list[TaskRow] = []
    people: list[PersonRow] = []
    # Photo-target state: when > 0 the upload card is visible at the top of the
    # Tasks page, primed to attach a photo to this task on next file selection.
    photo_target_task_id: int = 0
    photo_target_title: str = ""
    photo_uploading: bool = False
    photo_error: str = ""

    # Edit-task dialog state. `editing_task_id` doubles as open/close flag.
    editing_task_id: int = 0
    editing_task_title: str = ""
    editing_task_description: str = ""
    editing_task_assignee_name: str = "Unassigned"
    editing_task_has_due: bool = False
    editing_task_due_date: str = ""
    edit_task_error: str = ""

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self, read="chores")
        if redir is not None:
            return redir
        chores_db.init_db()
        self.people = chores_db.list_people()
        self._refresh()

    @rx.var
    def filter_options(self) -> list[str]:
        labels = ["All open", "Unassigned"]
        labels.extend(p["name"] for p in self.people)
        labels.append("Completed")
        return labels

    @rx.var
    def assignee_options(self) -> list[str]:
        return ["Unassigned"] + [p["name"] for p in self.people]

    # ---- Edit-task dialog -----
    @rx.event
    def open_task_edit(self, task_id: int):
        task = next(
            (t for t in self.tasks if int(t["id"]) == int(task_id)), None
        )
        if task is None:
            return
        self.editing_task_id = int(task_id)
        self.editing_task_title = task.get("title") or ""
        self.editing_task_description = task.get("description") or ""
        self.editing_task_assignee_name = (
            task.get("assignee_label") or "Unassigned"
        )
        existing_due = task.get("due_date") or ""
        self.editing_task_has_due = bool(existing_due)
        self.editing_task_due_date = (
            existing_due if existing_due else date.today().isoformat()
        )
        self.edit_task_error = ""

    @rx.event
    def close_task_edit(self):
        self.editing_task_id = 0
        self.edit_task_error = ""

    @rx.event
    def handle_task_edit_open_change(self, is_open: bool):
        if not is_open:
            self.close_task_edit()

    @rx.event
    def set_editing_task_title(self, v: str):
        self.editing_task_title = v
        if self.edit_task_error:
            self.edit_task_error = ""

    @rx.event
    def set_editing_task_description(self, v: str):
        self.editing_task_description = v

    @rx.event
    def set_editing_task_assignee(self, v: str):
        self.editing_task_assignee_name = v

    @rx.event
    def set_editing_task_has_due(self, v: bool):
        self.editing_task_has_due = v

    @rx.event
    def set_editing_task_due_date(self, v: str):
        self.editing_task_due_date = v

    @rx.event
    async def save_task_edit(self):
        if not await _require_write(self, "chores"):
            return
        title = self.editing_task_title.strip()
        if not title:
            self.edit_task_error = "Title can't be empty."
            return
        assignee_id: Optional[int] = None
        if self.editing_task_assignee_name != "Unassigned":
            p = next(
                (
                    p
                    for p in self.people
                    if p["name"] == self.editing_task_assignee_name
                ),
                None,
            )
            if p:
                assignee_id = int(p["id"])
        try:
            chores_db.update_task(
                int(self.editing_task_id),
                title,
                self.editing_task_description or None,
                assignee_id,
                (
                    self.editing_task_due_date
                    if self.editing_task_has_due
                    else None
                ),
            )
        except Exception as exc:
            self.edit_task_error = _safe_error(exc, "Could not save task.")
            return
        self.editing_task_id = 0
        self.edit_task_error = ""
        self._refresh()

    @rx.event
    def set_filter(self, value: str):
        self.filter_value = value
        self._refresh()

    @rx.event
    async def toggle_complete(self, task_id: int):
        if not await _require_write(self, "chores"):
            return
        # Optimistic: flip the checkbox locally, yield, then write to DB
        # off-thread. Roll back on failure.
        snapshot = [dict(t) for t in self.tasks]
        target_already_done: Optional[bool] = None
        for t in self.tasks:
            if int(t["id"]) == int(task_id):
                target_already_done = bool(t["completed"])
                t["completed"] = not target_already_done
                break
        self.tasks = list(self.tasks)
        if target_already_done is None:
            return
        yield
        advanced_to: Optional[int] = None
        try:
            if target_already_done:
                await asyncio.to_thread(
                    chores_db.mark_complete, int(task_id), False
                )
            else:
                advanced_to = await asyncio.to_thread(
                    chores_db.mark_complete_and_advance, int(task_id)
                )
        except Exception:
            self.tasks = snapshot
            yield rx.toast.error("Couldn't update task. Try again.")
            return
        self._refresh()
        if advanced_to:
            yield rx.toast.success(
                "Done — next occurrence scheduled.", duration=3000,
            )

    @rx.event
    async def delete_task(self, task_id: int):
        if not await _require_write(self, "chores"):
            return
        task = chores_db.get_task(int(task_id))
        chores_db.delete_task(int(task_id))
        self._refresh()
        if task:
            undo = await self.get_state(UndoState)
            undo.arm(
                "task",
                {
                    "title": task.get("title") or "",
                    "description": task.get("description"),
                    "assigned_to": task.get("assigned_to"),
                    "due_date": task.get("due_date"),
                    "recurrence": task.get("recurrence"),
                    "parent_task_id": task.get("parent_task_id"),
                },
                f"Deleted {task.get('title') or 'task'}.",
            )

    @rx.event
    def start_photo(self, task_id: int):
        """Reveal the upload card primed for `task_id`."""
        task = next(
            (t for t in self.tasks if int(t["id"]) == int(task_id)), None
        )
        if task is None:
            return
        self.photo_target_task_id = int(task_id)
        self.photo_target_title = task["title"]
        self.photo_error = ""

    @rx.event
    def cancel_photo(self):
        self.photo_target_task_id = 0
        self.photo_target_title = ""
        self.photo_error = ""

    @rx.event
    def clear_photo(self, task_id: int):
        """Remove the proof photo from a task (DB row stays; file untouched)."""
        chores_db.set_task_photo(int(task_id), None)
        self._refresh()

    @rx.event
    async def handle_photo_upload(self, files: list[rx.UploadFile]):
        if not files or not self.photo_target_task_id:
            return
        if not await _require_write(self, "chores"):
            self.photo_error = "You don't have chores write access."
            return
        self.photo_uploading = True
        yield
        try:
            f = files[0]
            data = await f.read()
            config.CHORE_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
            import secrets as _sec

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = (
                config.CHORE_PHOTOS_DIR
                / f"{ts}_{_sec.token_hex(8)}.jpg"
            )
            await asyncio.to_thread(_save_oriented_jpeg, data, out_path)
            chores_db.set_task_photo(
                int(self.photo_target_task_id), str(out_path)
            )
        except Exception as exc:
            self.photo_error = (
                _safe_error(exc, "Photo upload failed. Try again.")
            )
            self.photo_uploading = False
            return
        self.photo_uploading = False
        self.photo_target_task_id = 0
        self.photo_target_title = ""
        self.photo_error = ""
        self._refresh()

    def _refresh(self):
        if self.filter_value == "All open":
            tasks = chores_db.list_tasks(assigned_to=None, include_completed=False)
        elif self.filter_value == "Unassigned":
            tasks = chores_db.list_tasks(assigned_to=0, include_completed=False)
        elif self.filter_value == "Completed":
            tasks = chores_db.list_tasks(only_completed=True)
        else:
            person = next(
                (p for p in self.people if p["name"] == self.filter_value), None
            )
            if person:
                tasks = chores_db.list_tasks(
                    assigned_to=int(person["id"]), include_completed=False
                )
            else:
                tasks = []
        rows: list[TaskRow] = []
        for t in tasks:
            photo_path = t.get("completion_photo_path") or ""
            rows.append(
                {
                    "id": int(t["id"]),
                    "title": t["title"] or "",
                    "description": t.get("description") or "",
                    "due_date": t.get("due_date") or "",
                    "completed": int(t["completed"] or 0),
                    "completed_bool": bool(t["completed"]),
                    "due_display": _format_due(
                        t.get("due_date"), bool(t["completed"])
                    ),
                    "assignee_label": t.get("assignee_name") or "Unassigned",
                    "assignee_color": t.get("assignee_color") or "#888888",
                    "completion_photo_path": photo_path,
                    "completion_photo_url": _chore_photo_url(photo_path),
                    "has_photo": bool(photo_path),
                }
            )
        self.tasks = rows


# ---- Chores Add Task ---------------------------------------------------------
class ChoresAddState(rx.State):
    title: str = ""
    description: str = ""
    assignee_name: str = "Unassigned"
    has_due: bool = False
    due_date: str = ""
    template: str = ""
    people: list[PersonRow] = []
    success: str = ""
    # Recurrence: "" = one-shot, otherwise one of the codes the DB layer
    # understands ('daily', 'weekly', 'monthly', 'yearly', or weekly:X,Y,Z).
    recurrence: str = ""

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self, read="chores")
        if redir is not None:
            return redir
        chores_db.init_db()
        self.people = chores_db.list_people()
        if not self.due_date:
            self.due_date = date.today().isoformat()
        # PWA Web Share Target handoff: /chores/add?text=... prefills title.
        try:
            shared = (self.router.page.params.get("text") or "").strip()
        except Exception:
            shared = ""
        if shared and not self.title.strip():
            first = shared.splitlines()[0].strip()[:200]
            self.title = first or shared[:200]
            rest = "\n".join(shared.splitlines()[1:]).strip()
            if rest and not self.description:
                self.description = rest

    @rx.var
    def assignee_options(self) -> list[str]:
        return ["Unassigned"] + [p["name"] for p in self.people]

    @rx.var
    def template_options(self) -> list[str]:
        # First entry is a placeholder — picking it doesn't fill the title.
        return ["— Pick a common chore —"] + sorted(config.CHORE_TEMPLATES)

    @rx.event
    def set_template(self, value: str):
        self.template = value
        if value and not value.startswith("—"):
            self.title = value

    @rx.event
    def set_title(self, value: str):
        self.title = value
        if self.success:
            self.success = ""

    @rx.event
    def set_description(self, value: str):
        self.description = value

    @rx.event
    def set_assignee(self, value: str):
        self.assignee_name = value

    @rx.event
    def set_has_due(self, value: bool):
        self.has_due = value

    @rx.event
    def set_due_date(self, value: str):
        self.due_date = value

    # Map between the human label shown in the picker and the rule string
    # the DB layer understands. Kept as a class attr so the UI can iterate
    # without round-tripping to the server.
    _RECURRENCE_LABELS = {
        "": "Doesn't repeat",
        "daily": "Daily",
        "weekly": "Weekly",
        "weekly:MON,WED,FRI": "Weekly · Mon / Wed / Fri",
        "weekly:SAT,SUN": "Weekends only",
        "monthly": "Monthly",
        "yearly": "Yearly",
    }

    @rx.var
    def recurrence_options(self) -> list[str]:
        return list(self._RECURRENCE_LABELS.values())

    @rx.var
    def recurrence_label(self) -> str:
        return self._RECURRENCE_LABELS.get(
            self.recurrence, "Doesn't repeat",
        )

    @rx.event
    def set_recurrence_label(self, label: str):
        # Reverse-lookup label → code.
        for code, lbl in self._RECURRENCE_LABELS.items():
            if lbl == label:
                self.recurrence = code
                return
        self.recurrence = ""

    @rx.event
    async def submit(self):
        if not await _require_write(self, "chores"):
            return
        if not self.title.strip():
            return
        assignee_id: Optional[int] = None
        if self.assignee_name != "Unassigned":
            p = next(
                (p for p in self.people if p["name"] == self.assignee_name), None
            )
            if p:
                assignee_id = int(p["id"])
        chores_db.add_task(
            title=self.title,
            description=self.description or None,
            assigned_to=assignee_id,
            due_date=self.due_date if self.has_due else None,
            recurrence=self.recurrence or None,
        )
        added_title = self.title.strip()
        self.success = ""
        self.title = ""
        self.description = ""
        self.recurrence = ""
        yield rx.toast.success(f'Added: "{added_title}"', duration=3000)


# ---- Chores People -----------------------------------------------------------
class ChoresPeopleState(rx.State):
    people: list[PersonRow] = []
    new_name: str = ""
    new_color: str = "#FF4136"
    error: str = ""

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self, read="chores")
        if redir is not None:
            return redir
        chores_db.init_db()
        self._refresh()

    @rx.var
    def color_options(self) -> list[str]:
        return config.PERSON_COLORS

    @rx.event
    def set_new_name(self, value: str):
        self.new_name = value
        self.error = ""

    @rx.event
    def set_new_color(self, value: str):
        self.new_color = value

    @rx.event
    def add_person(self):
        if not self.new_name.strip():
            self.error = "Name can't be empty."
            return
        try:
            chores_db.add_person(self.new_name.strip())
            self.new_name = ""
            self.error = ""
            self._refresh()
        except Exception as exc:
            self.error = _safe_error(exc, "Could not add.")

    @rx.event
    def delete_person(self, person_id: int):
        chores_db.delete_person(int(person_id))
        self._refresh()

    def _refresh(self):
        people = chores_db.list_people()
        for p in people:
            p["task_count"] = chores_db.person_task_count(int(p["id"]))
        self.people = people


# ---- Announcements -----------------------------------------------------------
class AnnouncementRow(TypedDict, total=False):
    id: int
    title: str
    body: str
    pinned: int
    pinned_bool: bool
    expires_at: str
    created_at: str
    posted_by_name: str
    posted_by_color: str


class AnnouncementsState(rx.State):
    items: list[AnnouncementRow] = []
    new_title: str = ""
    new_body: str = ""
    new_pinned: bool = False
    error: str = ""

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        ann_db.init_db()
        chores_db.init_db()
        self._refresh()

    @rx.event
    def set_new_title(self, value: str):
        self.new_title = value


    @rx.event
    def set_new_body(self, value: str):
        self.new_body = value

    @rx.event
    def set_new_pinned(self, value: bool):
        self.new_pinned = value

    @rx.event
    async def add(self):
        if not self.new_title.strip():
            self.error = "Title required."
            return
        auth = await self.get_state(AuthState)
        ann_db.add_announcement(
            title=self.new_title,
            body=self.new_body or None,
            posted_by=auth.current_user_id or None,
            pinned=self.new_pinned,
        )
        self.new_title = ""
        self.new_body = ""
        self.new_pinned = False
        self.error = ""
        self._refresh()

    @rx.event
    def toggle_pinned(self, ann_id: int):
        ann_db.toggle_pinned(int(ann_id))
        self._refresh()

    @rx.event
    async def delete(self, ann_id: int):
        row = next(
            (a for a in ann_db.list_announcements(include_expired=True)
             if int(a['id']) == int(ann_id)),
            None,
        )
        ann_db.delete_announcement(int(ann_id))
        self._refresh()
        if row:
            undo = await self.get_state(UndoState)
            undo.arm(
                "announcement",
                {
                    "title": row.get("title") or "",
                    "body": row.get("body"),
                    "posted_by": row.get("posted_by"),
                    "pinned": bool(row.get("pinned")),
                },
                f"Deleted announcement: {row.get('title') or ''}.",
            )

    def _refresh(self):
        raw = ann_db.list_announcements()
        people_by_id = {int(p["id"]): p for p in chores_db.list_people()}
        out: list[AnnouncementRow] = []
        for a in raw:
            p = people_by_id.get(int(a["posted_by"])) if a.get("posted_by") else None
            out.append(
                {
                    "id": int(a["id"]),
                    "title": a["title"],
                    "body": a.get("body") or "",
                    "pinned": int(a["pinned"] or 0),
                    "pinned_bool": bool(a["pinned"]),
                    "expires_at": a.get("expires_at") or "",
                    "created_at": a["created_at"],
                    "posted_by_name": (p["name"] if p else "") or "",
                    "posted_by_color": (p["color"] if p else "#888888") or "#888888",
                }
            )
        self.items = out


# ---- Assistant (JARVIS-style agentic chat) -----------------------------------
class ChatTurnEntry(TypedDict, total=False):
    """One unit in the rendered conversation. `kind` is:
      - 'user': a message you typed
      - 'assistant': JARVIS's final text response
      - 'tool_call': a tool the assistant invoked (rendered as a chip)
      - 'tool_result': we don't render these; they live in the trace for
        the LLM to read but the UI elides them.
    """
    kind: str
    text: str
    name: str         # tool name when kind == 'tool_call'
    args_json: str    # pretty-printed args for the chip hover


class AssistantState(rx.State):
    """JARVIS chat. Holds the visible transcript and the wire-format
    message list separately — the LLM doesn't need to see tool chips, and
    the UI doesn't need to see raw tool results."""

    # Transcript shown to the user. Built as the conversation progresses.
    transcript: list[ChatTurnEntry] = []
    # The raw messages sent to the model (user + assistant text turns
    # only; tool calls go in/out via the trace each call).
    wire_messages: list[dict] = []
    input_text: str = ""
    sending: bool = False

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        # Greet on first load.
        if not self.transcript:
            self.transcript = [{
                "kind": "assistant",
                "text": (
                    "At your service. Ask about inventory, schedule, "
                    "meals, chores — or tell me to do something."
                ),
            }]

    @rx.event
    def set_input(self, value: str):
        self.input_text = value

    @rx.event
    def clear_chat(self):
        self.transcript = []
        self.wire_messages = []
        self.input_text = ""
        self.sending = False

    @rx.event
    async def send(self):
        text = (self.input_text or "").strip()
        if not text or self.sending:
            return
        # Append the user turn to both the transcript and the wire log.
        self.transcript = self.transcript + [{"kind": "user", "text": text}]
        self.wire_messages = self.wire_messages + [
            {"role": "user", "content": text},
        ]
        self.input_text = ""
        self.sending = True
        yield

        auth = await self.get_state(AuthState)
        user_name = auth.current_user_name or None

        try:
            trace = await asyncio.to_thread(
                assistant_chat.turn,
                list(self.wire_messages),
                user_name,
            )
        except Exception as exc:
            import traceback, sys
            traceback.print_exc(file=sys.stderr)
            self.transcript = self.transcript + [{
                "kind": "assistant",
                "text": (
                    "Something went sideways with the LLM. Check the "
                    "server log and Settings → API."
                ),
            }]
            self.sending = False
            return

        # Translate trace into transcript entries; collect the final
        # assistant text to extend wire_messages.
        new_entries: list[ChatTurnEntry] = []
        final_text = ""
        for entry in trace:
            kind = entry.get("kind")
            if kind == "tool_call":
                new_entries.append({
                    "kind": "tool_call",
                    "name": entry.get("name") or "",
                    "args_json": _short_json(entry.get("args") or {}),
                })
            elif kind == "assistant":
                final_text = entry.get("text") or ""
                if final_text:
                    new_entries.append({
                        "kind": "assistant",
                        "text": final_text,
                    })

        self.transcript = self.transcript + new_entries
        if final_text:
            self.wire_messages = self.wire_messages + [
                {"role": "assistant", "content": final_text},
            ]
        self.sending = False


def _short_json(obj) -> str:
    """Compact JSON for tool-call chip tooltips. Truncated to 120 chars."""
    try:
        s = json.dumps(obj, default=str)
    except Exception:
        s = str(obj)
    return s[:120] + ("…" if len(s) > 120 else "")


# ---- Notes -------------------------------------------------------------------
class NoteRow(TypedDict, total=False):
    id: int
    title: str
    body: str
    pinned: int
    pinned_bool: bool
    created_at: str
    updated_at: str


class ShareHandoffState(rx.State):
    """Backs the /share-handoff disambiguator page that the PWA Web
    Share Target redirects to when the user shares text (no image).
    Three buttons send the text on to notes / groceries / chores.
    """
    shared_text: str = ""

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        try:
            self.shared_text = (
                self.router.page.params.get("text") or ""
            ).strip()
        except Exception:
            self.shared_text = ""

    @rx.event
    async def save_as_note(self):
        notes = await self.get_state(NotesState)
        return await notes.create_from_shared(self.shared_text)

    @rx.event
    async def add_to_groceries(self):
        groc = await self.get_state(GroceriesState)
        return await groc.add_from_shared(self.shared_text)

    @rx.event
    def create_task(self):
        from urllib.parse import urlencode, quote
        if not self.shared_text:
            return rx.redirect("/chores/add")
        params = urlencode({"text": self.shared_text}, quote_via=quote)
        return rx.redirect(f"/chores/add?{params}")


class NotesState(rx.State):
    items: list[NoteRow] = []
    new_title: str = ""
    new_body: str = ""
    new_pinned: bool = False
    error: str = ""

    # Edit-in-place dialog state. `editing_id` doubles as the open/closed flag.
    editing_id: int = 0
    edit_title: str = ""
    edit_body: str = ""

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        notes_db.init_db()
        self._refresh()

    @rx.event
    def set_new_title(self, value: str):
        self.new_title = value
        self.error = ""

    @rx.event
    async def maybe_submit_on_enter(self, key: str):
        # Title input's onKeyDown hook: Enter saves a quick note
        # without forcing the user to mouse to Add note. Skip if
        # the body has content (user is probably composing).
        if key != "Enter":
            return
        if not self.new_title.strip():
            return
        if self.new_body.strip():
            return
        async for ev in self.add():
            yield ev


    @rx.event
    def set_new_body(self, value: str):
        self.new_body = value

    @rx.event
    def set_new_pinned(self, value: bool):
        self.new_pinned = value

    @rx.event
    async def create_from_shared(self, text: str):
        """Create a note straight from a Web Share Target payload, then
        redirect to /notes. First non-empty line becomes the title;
        remainder becomes the body."""
        body_text = (text or "").strip()
        if not body_text:
            return rx.redirect("/notes")
        lines = body_text.splitlines()
        first = lines[0].strip()
        rest = "\n".join(lines[1:]).strip()
        title = first[:120] if first else "Shared note"
        body = rest if rest else (first if title != first else None)
        auth = await self.get_state(AuthState)
        notes_db.add_note(
            title=title,
            body=body,
            author_id=auth.current_user_id or None,
            pinned=False,
        )
        return rx.redirect("/notes")

    @rx.event
    async def add(self):
        if not self.new_title.strip():
            self.error = "Title required."
            return
        auth = await self.get_state(AuthState)
        notes_db.add_note(
            title=self.new_title,
            body=self.new_body or None,
            author_id=auth.current_user_id or None,
            pinned=self.new_pinned,
        )
        self.new_title = ""
        self.new_body = ""
        self.new_pinned = False
        self.error = ""
        self._refresh()

    @rx.event
    def toggle_pinned(self, nid: int):
        notes_db.toggle_pinned(int(nid))
        self._refresh()

    @rx.event
    async def delete(self, nid: int):
        row = notes_db.get_note(int(nid))
        notes_db.delete_note(int(nid))
        self._refresh()
        if row:
            undo = await self.get_state(UndoState)
            undo.arm(
                "note",
                {
                    "title": row.get("title") or "",
                    "body": row.get("body"),
                    "author_id": row.get("author_id"),
                    "pinned": bool(row.get("pinned")),
                },
                f"Deleted note: {row.get('title') or ''}.",
            )

    # ---- Edit dialog ----
    @rx.event
    def open_edit(self, nid: int):
        note = notes_db.get_note(int(nid))
        if not note:
            return
        self.editing_id = int(note["id"])
        self.edit_title = note.get("title") or ""
        self.edit_body = note.get("body") or ""

    @rx.event
    def close_edit(self):
        self.editing_id = 0
        self.edit_title = ""
        self.edit_body = ""

    @rx.event
    def set_edit_title(self, value: str):
        self.edit_title = value

    @rx.event
    def set_edit_body(self, value: str):
        self.edit_body = value

    @rx.event
    def save_edit(self):
        if not self.editing_id:
            return
        if not self.edit_title.strip():
            return
        notes_db.update_note(
            int(self.editing_id),
            title=self.edit_title,
            body=self.edit_body,
        )
        self.close_edit()
        self._refresh()

    # ---- AI polish ---------------------------------------------------
    polishing: bool = False

    async def _polish_text(self, raw: str) -> Optional[str]:
        """Run a body of text through the configured LLM with a tight
        'clean up dictation' prompt. Returns the cleaned text or None on
        failure. Always runs in a worker thread so it doesn't block."""
        text = (raw or "").strip()
        if not text:
            return None
        from inventory import recognize as _recog

        prompt = (
            "You are cleaning up a voice-dictated note. The user spoke "
            "into a phone and got an unstructured transcript. Rewrite it "
            "into clean, readable prose:\n"
            " - fix obvious speech-to-text errors and homophone slips\n"
            " - add punctuation and paragraph breaks\n"
            " - turn lists / itemized points into Markdown-style bullets\n"
            " - infer obvious missing context ONLY when very confident\n"
            "Don't invent facts. Don't add commentary. Don't echo a "
            "preamble. Return ONLY the cleaned-up note body.\n\n"
            "--- transcript ---\n"
            f"{text}\n"
            "--- end transcript ---"
        )

        def _run() -> str:
            provider, key, model = _recog._get_llm_config()
            if provider == "openai":
                client = _recog._get_openai_client(key)
                resp = _recog._call_with_retry(
                    lambda: client.chat.completions.create(
                        model=model,
                        max_completion_tokens=1024,
                        messages=[
                            {"role": "user", "content": prompt},
                        ],
                    )
                )
                return (resp.choices[0].message.content or "").strip()
            client = _recog._get_anthropic_client(key)
            msg = _recog._call_with_retry(
                lambda: client.messages.create(
                    model=model,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
            )
            return "".join(
                b.text for b in msg.content
                if getattr(b, "type", None) == "text"
            ).strip()

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            import sys, traceback
            traceback.print_exc(file=sys.stderr)
            return None

    @rx.event
    async def polish_new_body(self):
        """Clean up the new-note body via the LLM. No-op if empty."""
        if self.polishing:
            return
        if not (self.new_body or "").strip():
            yield rx.toast.info(
                "Type or dictate something first.", duration=2500,
            )
            return
        self.polishing = True
        yield
        cleaned = await self._polish_text(self.new_body)
        self.polishing = False
        if not cleaned:
            yield rx.toast.error(
                "Polish failed — see server log.", duration=3500,
            )
            return
        self.new_body = cleaned
        yield rx.toast.success("Polished by AI.", duration=2500)

    @rx.event
    async def polish_edit_body(self):
        """Clean up the in-dialog edit body via the LLM."""
        if self.polishing:
            return
        if not (self.edit_body or "").strip():
            yield rx.toast.info(
                "There's nothing to polish.", duration=2500,
            )
            return
        self.polishing = True
        yield
        cleaned = await self._polish_text(self.edit_body)
        self.polishing = False
        if not cleaned:
            yield rx.toast.error(
                "Polish failed — see server log.", duration=3500,
            )
            return
        self.edit_body = cleaned
        yield rx.toast.success("Polished by AI.", duration=2500)

    def _refresh(self):
        raw = notes_db.list_notes()
        self.items = [
            {
                "id": int(n["id"]),
                "title": n["title"],
                "body": n.get("body") or "",
                "pinned": int(n["pinned"] or 0),
                "pinned_bool": bool(n["pinned"]),
                "created_at": n["created_at"],
                "updated_at": n["updated_at"],
            }
            for n in raw
        ]


# ---- Groceries ---------------------------------------------------------------
class GroceryRow(TypedDict, total=False):
    id: int
    name: str
    quantity: str
    notes: str
    purchased: int
    purchased_bool: bool
    created_at: str


class GroceriesState(rx.State):
    items: list[GroceryRow] = []
    new_name: str = ""
    new_quantity: str = ""
    error: str = ""

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        groc_db.init_db()
        self._refresh()

    @rx.event
    def set_new_name(self, value: str):
        self.new_name = value
        self.error = ""

    @rx.event
    def set_new_quantity(self, value: str):
        self.new_quantity = value

    @rx.event
    async def add(self):
        if not self.new_name.strip():
            self.error = "Name required."
            return
        auth = await self.get_state(AuthState)
        groc_db.add_grocery(
            name=self.new_name,
            quantity=self.new_quantity or None,
            added_by=auth.current_user_id or None,
        )
        self.new_name = ""
        self.new_quantity = ""
        self.error = ""
        self._refresh()

    @rx.event
    async def add_from_shared(self, text: str):
        """PWA Web Share Target sink — add the shared text as a grocery
        line and bounce to /groceries."""
        name = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
        name = name[:160].strip()
        if not name:
            return rx.redirect("/groceries")
        auth = await self.get_state(AuthState)
        groc_db.add_grocery(
            name=name,
            quantity=None,
            added_by=auth.current_user_id or None,
        )
        return rx.redirect("/groceries")

    @rx.event
    async def toggle_purchased(self, gid: int):
        # Optimistic: flip the row in self.items, yield to push the change,
        # then run the DB write off-thread. Roll back on failure.
        snapshot = [dict(g) for g in self.items]
        new_purchased = None
        for g in self.items:
            if int(g["id"]) == int(gid):
                new_purchased = not bool(g["purchased"])
                g["purchased"] = new_purchased
                break
        self.items = list(self.items)
        if new_purchased is None:
            return
        yield
        try:
            await asyncio.to_thread(
                groc_db.set_purchased, int(gid), bool(new_purchased)
            )
        except Exception:
            self.items = snapshot
            yield rx.toast.error("Couldn't update item. Try again.")
            return
        self._refresh()

    @rx.event
    async def delete(self, gid: int):
        row = next(
            (g for g in groc_db.list_groceries(include_purchased=True)
             if int(g['id']) == int(gid)),
            None,
        )
        groc_db.delete_grocery(int(gid))
        self._refresh()
        if row:
            undo = await self.get_state(UndoState)
            undo.arm(
                "grocery",
                {
                    "name": row.get("name") or "",
                    "quantity": row.get("quantity"),
                    "notes": row.get("notes"),
                    "from_meal_id": row.get("from_meal_id"),
                },
                f"Removed {row.get('name') or 'item'}.",
            )

    @rx.event
    def clear_purchased(self):
        groc_db.clear_purchased()
        self._refresh()

    def _refresh(self):
        raw = groc_db.list_groceries(include_purchased=True)
        self.items = [
            {
                "id": int(g["id"]),
                "name": g["name"],
                "quantity": g.get("quantity") or "",
                "notes": g.get("notes") or "",
                "purchased": int(g["purchased"] or 0),
                "purchased_bool": bool(g["purchased"]),
                "created_at": g["created_at"],
            }
            for g in raw
        ]


# ---- Meals -------------------------------------------------------------------
class MealRow(TypedDict, total=False):
    id: int
    name: str
    meal_date: str
    meal_type: str
    notes: str
    ingredients_text: str  # comma-joined for display
    created_at: str


class RecipeRow(TypedDict, total=False):
    id: int
    name: str
    ingredients_text: str  # comma-joined for display


class CookableRecipe(TypedDict, total=False):
    id: int
    name: str
    ingredients_text: str
    have: int
    missing: int
    missing_names: str
    fully_stocked: bool


class MealsState(rx.State):
    items: list[MealRow] = []
    recipes: list[RecipeRow] = []
    cookable: list[CookableRecipe] = []
    new_name: str = ""
    new_date: str = ""
    new_type: str = "dinner"
    new_notes: str = ""
    new_ingredients_text: str = ""  # newline-separated ingredient names
    new_template: str = ""
    last_added_message: str = ""
    error: str = ""

    # Lightweight feedback for the "Save as recipe" action (separate from the
    # main meal-plan callout so users see which action confirmed).
    recipe_error: str = ""
    recipe_message: str = ""

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        meals_db.init_db()
        groc_db.init_db()
        inv_db.init_db()
        if not self.new_date:
            self.new_date = date.today().isoformat()
        self._refresh()
        self._refresh_recipes()
        self._refresh_cookable()

    @rx.event
    async def add_missing_to_groceries(self, recipe_id: int):
        """Diff a recipe's ingredients against inventory; add any
        missing ones to the active grocery list. Idempotent — already-
        active grocery rows with the same name are left alone. Tagged
        with from_meal_id so the grocery row can link back to the
        recipe that needed it."""
        if not await _require_write(self, "inventory"):
            return
        from groceries import db as groc_db
        recipe = next(
            (r for r in meals_db.list_recipes() if int(r["id"]) == int(recipe_id)),
            None,
        )
        if not recipe:
            yield rx.toast.error("Recipe not found.")
            return
        ings = [i for i in (recipe.get("ingredients") or []) if i.strip()]
        missing = [i for i in ings if not inv_db.has_item(i)]
        if not missing:
            yield rx.toast.success("All ingredients on hand already.")
            return
        # Don't duplicate items already active on the shopping list.
        try:
            active_names = {
                (g.get("name") or "").strip().lower()
                for g in groc_db.list_groceries(include_purchased=False)
            }
        except Exception:
            active_names = set()
        added = 0
        for ing in missing:
            if ing.strip().lower() in active_names:
                continue
            try:
                groc_db.add_grocery(name=ing, from_meal_id=int(recipe_id))
                added += 1
            except Exception:
                pass
        if added:
            yield rx.toast.success(
                f"Added {added} ingredient(s) to the shopping list."
            )
        else:
            yield rx.toast.info(
                "All missing items were already on the shopping list."
            )
        # Refresh cookable so the UI reflects the new shopping status.
        self._refresh_cookable()

    def _refresh_cookable(self):
        """Compute which saved recipes are cookable right now. A recipe is
        'fully stocked' if every ingredient matches something in inventory;
        otherwise we list the missing ones so the user can act on it."""
        raw = meals_db.list_recipes()
        rows: list[CookableRecipe] = []
        for r in raw:
            ings = [i for i in (r.get("ingredients") or []) if i.strip()]
            if not ings:
                continue
            have, missing = [], []
            for i in ings:
                if inv_db.has_item(i):
                    have.append(i)
                else:
                    missing.append(i)
            rows.append({
                "id": int(r["id"]),
                "name": r["name"],
                "ingredients_text": ", ".join(ings),
                "have": len(have),
                "missing": len(missing),
                "missing_names": ", ".join(missing),
                "fully_stocked": not missing,
            })
        # Show fully-stocked first, then those with the fewest missing.
        rows.sort(key=lambda r: (not r["fully_stocked"], r["missing"]))
        self.cookable = rows

    @rx.var
    def meal_type_options(self) -> list[str]:
        return config.MEAL_TYPES

    @rx.var
    def template_options(self) -> list[str]:
        names = [r["name"] for r in self.recipes]
        if not names:
            return ["— No saved recipes yet —"]
        return ["— Pick a saved recipe —"] + names

    @rx.event
    def set_template(self, value: str):
        self.new_template = value
        if value and not value.startswith("—"):
            tmpl = meals_db.get_recipe_by_name(value)
            if tmpl:
                self.new_name = tmpl["name"]
                self.new_ingredients_text = "\n".join(
                    tmpl.get("ingredients") or []
                )

    # ---- Recipe management ----
    def _current_ingredients(self) -> list[str]:
        return [
            line.strip()
            for line in self.new_ingredients_text.splitlines()
            if line.strip()
        ]

    @rx.event
    def save_as_recipe(self):
        """Save the current name + ingredients as a reusable recipe.
        Does NOT add anything to the meal plan or shopping list."""
        name = self.new_name.strip()
        if not name:
            self.recipe_error = "Name required to save a recipe."
            self.recipe_message = ""
            return
        try:
            meals_db.add_recipe(name, self._current_ingredients())
        except Exception as exc:
            self.recipe_error = _safe_error(exc, "Could not save recipe.")
            self.recipe_message = ""
            return
        self.recipe_message = ""
        self.recipe_error = ""
        self.last_added_message = ""
        yield rx.toast.success(f"Saved recipe: {name}", duration=3000)
        self._refresh_recipes()

    @rx.event
    def save_recipe_and_add(self):
        """Save the recipe AND plan it as a meal in one click."""
        name = self.new_name.strip()
        if not name:
            self.error = "Name required."
            return
        try:
            meals_db.add_recipe(name, self._current_ingredients())
            self.recipe_message = ""
            self.recipe_error = ""
            yield rx.toast.success(f"Saved recipe: {name}", duration=3000)
        except Exception as exc:
            # If the recipe already exists or save fails, surface a soft
            # warning but still proceed with planning.
            self.recipe_error = _safe_error(exc, "Recipe not saved.")
            self.recipe_message = ""
        self._refresh_recipes()
        # Re-use the existing add() logic for planning + grocery sync.
        return MealsState.add

    @rx.event
    async def delete_recipe(self, rid: int):
        row = next(
            (r for r in meals_db.list_recipes()
             if int(r['id']) == int(rid)),
            None,
        )
        meals_db.delete_recipe(int(rid))
        self._refresh_recipes()
        if row:
            undo = await self.get_state(UndoState)
            undo.arm(
                "recipe",
                {
                    "name": row.get("name") or "",
                    "ingredients": row.get("ingredients") or [],
                },
                f"Deleted recipe: {row.get('name') or ''}.",
            )

    def _refresh_recipes(self):
        raw = meals_db.list_recipes()
        self.recipes = [
            {
                "id": int(r["id"]),
                "name": r["name"],
                "ingredients_text": ", ".join(r.get("ingredients") or []),
            }
            for r in raw
        ]

    @rx.event
    def set_new_name(self, v: str):
        self.new_name = v
        self.error = ""

    @rx.event
    def set_new_date(self, v: str):
        self.new_date = v

    @rx.event
    def set_new_type(self, v: str):
        self.new_type = v

    @rx.event
    def set_new_notes(self, v: str):
        self.new_notes = v

    @rx.event
    def set_new_ingredients_text(self, v: str):
        self.new_ingredients_text = v

    @rx.event
    def add(self):
        if not self.new_name.strip():
            self.error = "Name required."
            return
        ingredients = [
            line.strip()
            for line in self.new_ingredients_text.splitlines()
            if line.strip()
        ]
        meal_id = meals_db.add_meal(
            name=self.new_name,
            meal_date=self.new_date or None,
            meal_type=self.new_type,
            notes=self.new_notes or None,
            ingredients=ingredients,
        )

        # Auto-add missing ingredients to the grocery list.
        added_count = 0
        for ing in ingredients:
            try:
                if not inv_db.has_item(ing):
                    groc_db.add_grocery(name=ing, from_meal_id=meal_id)
                    added_count += 1
            except Exception:
                pass

        name_added = self.new_name.strip()
        msg = f"Added meal: {name_added}"
        if added_count:
            msg += (
                f". {added_count} missing ingredient(s) added to the "
                f"shopping list."
            )
        self.last_added_message = ""
        self.new_name = ""
        self.new_notes = ""
        self.new_ingredients_text = ""
        self.new_template = ""
        self.error = ""
        self._refresh()
        yield rx.toast.success(msg, duration=3500)

    @rx.event
    async def delete(self, mid: int):
        row = next(
            (m for m in meals_db.list_meals(upcoming_only=False)
             if int(m['id']) == int(mid)),
            None,
        )
        meals_db.delete_meal(int(mid))
        self._refresh()
        if row:
            undo = await self.get_state(UndoState)
            undo.arm(
                "meal",
                {
                    "name": row.get("name") or "",
                    "meal_date": row.get("meal_date"),
                    "meal_type": row.get("meal_type"),
                    "notes": row.get("notes"),
                    "ingredients": row.get("ingredients") or [],
                },
                f"Removed meal: {row.get('name') or ''}.",
            )

    def _refresh(self):
        raw = meals_db.list_meals(upcoming_only=True)
        self.items = [
            {
                "id": int(m["id"]),
                "name": m["name"],
                "meal_date": m.get("meal_date") or "",
                "meal_type": m.get("meal_type") or "",
                "notes": m.get("notes") or "",
                "ingredients_text": ", ".join(m.get("ingredients") or []),
                "created_at": m["created_at"],
            }
            for m in raw
        ]


# ---- Appointments ------------------------------------------------------------
class AppointmentRow(TypedDict, total=False):
    id: int
    title: str
    appointment_at: str
    location: str
    notes: str
    for_person_name: str
    for_person_color: str
    created_at: str


class AppointmentsState(rx.State):
    items: list[AppointmentRow] = []
    people: list[PersonRow] = []
    new_title: str = ""
    new_date: str = ""
    new_time: str = "09:00"
    new_location: str = ""
    new_notes: str = ""
    new_for_name: str = "Anyone"
    new_recurrence: str = ""
    error: str = ""

    _RECURRENCE_LABELS = {
        "": "Doesn't repeat",
        "daily": "Daily",
        "weekly": "Weekly",
        "monthly": "Monthly",
        "yearly": "Yearly",
    }

    @rx.var
    def recurrence_options(self) -> list[str]:
        return list(self._RECURRENCE_LABELS.values())

    @rx.var
    def recurrence_label(self) -> str:
        return self._RECURRENCE_LABELS.get(
            self.new_recurrence, "Doesn't repeat",
        )

    @rx.event
    def set_recurrence_label(self, label: str):
        for code, lbl in self._RECURRENCE_LABELS.items():
            if lbl == label:
                self.new_recurrence = code
                return
        self.new_recurrence = ""

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        appt_db.init_db()
        chores_db.init_db()
        self.people = chores_db.list_people()
        if not self.new_date:
            self.new_date = date.today().isoformat()
        self._refresh()

    @rx.var
    def for_options(self) -> list[str]:
        return ["Anyone"] + [p["name"] for p in self.people]

    @rx.event
    def set_new_title(self, v: str):
        self.new_title = v
        self.error = ""

    @rx.event
    def set_new_date(self, v: str):
        self.new_date = v

    @rx.event
    def set_new_time(self, v: str):
        self.new_time = v

    @rx.event
    def set_new_location(self, v: str):
        self.new_location = v

    @rx.event
    def set_new_notes(self, v: str):
        self.new_notes = v

    @rx.event
    def set_new_for(self, v: str):
        self.new_for_name = v

    @rx.event
    def add(self):
        if not self.new_title.strip():
            self.error = "Title required."
            return
        if not self.new_date:
            self.error = "Date required."
            return
        for_id = None
        if self.new_for_name != "Anyone":
            p = next(
                (p for p in self.people if p["name"] == self.new_for_name), None
            )
            if p:
                for_id = int(p["id"])
        appt_at = f"{self.new_date} {self.new_time}:00"
        appt_db.add_appointment(
            title=self.new_title,
            appointment_at=appt_at,
            location=self.new_location or None,
            notes=self.new_notes or None,
            for_person=for_id,
            recurrence=self.new_recurrence or None,
        )
        self.new_title = ""
        self.new_location = ""
        self.new_notes = ""
        self.new_recurrence = ""
        self.error = ""
        self._refresh()

    @rx.event
    async def delete(self, aid: int):
        row = appt_db.get_appointment(int(aid))
        appt_db.delete_appointment(int(aid))
        self._refresh()
        if row:
            undo = await self.get_state(UndoState)
            undo.arm(
                "appointment",
                {
                    "title": row.get("title") or "",
                    "appointment_at": row.get("appointment_at") or "",
                    "location": row.get("location"),
                    "notes": row.get("notes"),
                    "for_person": row.get("for_person"),
                    "recurrence": row.get("recurrence"),
                },
                f"Removed: {row.get('title') or 'appointment'}.",
            )

    def _refresh(self):
        raw = appt_db.list_appointments(upcoming_only=True)
        people_by_id = {int(p["id"]): p for p in self.people}
        out: list[AppointmentRow] = []
        for a in raw:
            p = (
                people_by_id.get(int(a["for_person"]))
                if a.get("for_person")
                else None
            )
            out.append(
                {
                    "id": int(a["id"]),
                    "title": a["title"],
                    "appointment_at": a["appointment_at"],
                    "location": a.get("location") or "",
                    "notes": a.get("notes") or "",
                    "for_person_name": (p["name"] if p else "") or "",
                    "for_person_color": (p["color"] if p else "#888888") or "#888888",
                    "created_at": a["created_at"],
                }
            )
        self.items = out


# ---- Inventory item detail (single-item view) --------------------------------
class ItemDetailState(rx.State):
    """State for the per-item detail page `/inventory/item/[id]`."""

    item_id: int = 0
    item: ItemRow = {}
    not_found: bool = False

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self, read="inventory")
        if redir is not None:
            return redir
        inv_db.init_db()
        raw_id = self.router.page.params.get("id", "")
        try:
            self.item_id = int(raw_id)
        except (TypeError, ValueError):
            self.item_id = 0
            self.not_found = True
            self.item = {}
            return
        item = inv_db.get_item(self.item_id)
        if not item:
            self.not_found = True
            self.item = {}
            return
        self.not_found = False
        self.item = _enrich_item_row(item)

    @rx.event
    async def delete_item(self):
        if not await _require_write(self, "inventory"):
            return
        if self.item_id:
            inv_db.delete_item(self.item_id)
        return rx.redirect("/inventory/browse")

    # ---- Expiration --------------------------------------------------
    expiry_input: str = ""

    @rx.event
    def set_expiry_input(self, v: str):
        self.expiry_input = v

    @rx.event
    async def save_expiry(self):
        if not await _require_write(self, "inventory"):
            return
        if not self.item_id:
            return
        inv_db.set_expires_at(int(self.item_id), self.expiry_input or None)
        item = inv_db.get_item(self.item_id)
        if item:
            self.item = _enrich_item_row(item)
        return rx.toast.success("Expiration updated", duration=2500)

    # ---- Loan tracking -----------------------------------------------
    loan_to_name: str = ""
    loan_notes: str = ""

    @rx.event
    def set_loan_to_name(self, v: str):
        self.loan_to_name = v

    @rx.event
    def set_loan_notes(self, v: str):
        self.loan_notes = v

    @rx.event
    async def loan_out(self):
        if not await _require_write(self, "inventory"):
            return
        if not self.item_id:
            return
        name = self.loan_to_name.strip()
        if not name:
            return rx.toast.error("Who did you loan it to?", duration=3000)
        inv_db.set_loan(int(self.item_id), None, name, self.loan_notes or None)
        item = inv_db.get_item(self.item_id)
        if item:
            self.item = _enrich_item_row(item)
        self.loan_to_name = ""
        self.loan_notes = ""
        return rx.toast.success(f"Loaned to {name}", duration=3000)

    @rx.event
    async def loan_return(self):
        if not await _require_write(self, "inventory"):
            return
        if not self.item_id:
            return
        inv_db.set_loan(int(self.item_id), None, None, None)
        item = inv_db.get_item(self.item_id)
        if item:
            self.item = _enrich_item_row(item)
        return rx.toast.success("Marked as returned", duration=2500)


# ---- Inventory edit dialog (shared between Search and Browse) ----------------
def _relative_ts(ts: str) -> str:
    """Render a SQLite-ish 'YYYY-MM-DD HH:MM:SS' timestamp as
    '2d ago' / '3h ago' / 'just now'. Falls back to the raw string."""
    if not ts:
        return ""
    try:
        when = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return ts
    delta = datetime.now() - when
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    days = secs // 86400
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def _format_history_row(row: dict) -> dict:
    """Turn an item_history row into the dict shape consumed by the UI."""
    kind = row.get("kind") or ""
    detail_obj = row.get("detail_obj")
    raw_detail = row.get("detail") or ""
    if kind == "created" and isinstance(detail_obj, dict):
        text = (
            f"Added (qty {detail_obj.get('qty', 1)}, "
            f"{detail_obj.get('room') or 'unknown room'})"
        )
    elif kind == "quantity" and isinstance(detail_obj, dict):
        text = (
            f"Quantity: {detail_obj.get('from')} → {detail_obj.get('to')}"
        )
    elif kind == "expires":
        text = f"Expires {raw_detail}" if raw_detail else "Expiry cleared"
    elif kind == "loan":
        text = f"Lent to {raw_detail or 'someone'}"
    elif kind == "return":
        text = "Returned"
    elif kind == "deleted":
        text = "Deleted"
    elif kind == "price" and isinstance(detail_obj, dict):
        price = detail_obj.get("price")
        text = f"Price set: ${price:.2f}" if price else "Price recorded"
        store = detail_obj.get("store")
        if store:
            text = f"{text} at {store}"
    elif kind == "warranty" and isinstance(detail_obj, dict):
        ru = detail_obj.get("return_until")
        wu = detail_obj.get("warranty_until")
        parts = []
        if ru:
            parts.append(f"return by {ru}")
        if wu:
            parts.append(f"warranty until {wu}")
        text = ", ".join(parts) or "Warranty updated"
    else:
        text = raw_detail or kind
    return {
        "kind": kind,
        "text": text,
        "ts_rel": _relative_ts(row.get("ts") or ""),
        "actor": row.get("actor_name") or "",
    }


class InventoryEditState(rx.State):
    """Drives the edit-item dialog. `editing_id` doubles as the open flag."""

    editing_id: int = 0
    editing_name: str = ""
    editing_quantity: int = 1
    editing_category: str = "other"
    editing_for_sale: bool = False
    editing_value: float = 0.0
    editing_room: str = ""
    editing_photo_id: int = 0
    editing_initial_room: str = ""  # the room when the dialog opened
    # Purchase / warranty subsection.
    editing_purchase_date: str = ""
    editing_purchase_price: float = 0.0
    editing_purchase_store: str = ""
    editing_return_until: str = ""
    editing_warranty_until: str = ""
    # History viewer data (loaded on open_edit).
    history_rows: list[dict[str, str]] = []
    error: str = ""
    # Room-change confirmation: when the user changes the room and >1
    # item shares the same photo, we stage the save and surface a
    # confirm dialog before applying.
    pending_room_change_count: int = 0
    pending_room_change_new_room: str = ""

    @rx.var
    def category_options(self) -> list[str]:
        return config.CATEGORIES

    @rx.var
    def room_options(self) -> list[str]:
        rooms = sorted(
            inv_db.list_room_names() or list(config.ROOMS), key=str.lower
        )
        return rooms

    @rx.event
    def open_edit(self, item_id: int):
        item = inv_db.get_item(int(item_id))
        if not item:
            return
        self.editing_id = int(item["id"])
        self.editing_name = item.get("name") or ""
        self.editing_quantity = int(item.get("quantity") or 1)
        self.editing_category = item.get("category") or "other"
        self.editing_for_sale = bool(item.get("for_sale"))
        self.editing_value = float(item.get("estimated_value") or 0)
        self.editing_room = item.get("room") or ""
        self.editing_initial_room = self.editing_room
        self.editing_photo_id = int(item.get("photo_id") or 0)
        self.editing_purchase_date = item.get("purchase_date") or ""
        self.editing_purchase_price = float(item.get("purchase_price") or 0)
        self.editing_purchase_store = item.get("purchase_store") or ""
        self.editing_return_until = item.get("return_until") or ""
        self.editing_warranty_until = item.get("warranty_until") or ""
        try:
            raw_hist = inv_db.item_history(int(item_id), limit=50)
        except Exception:
            raw_hist = []
        self.history_rows = [_format_history_row(r) for r in raw_hist]
        self.error = ""

    @rx.event
    def close_edit(self):
        self.editing_id = 0
        self.error = ""

    @rx.event
    def handle_open_change(self, is_open: bool):
        if not is_open:
            self.close_edit()

    @rx.event
    def set_editing_name(self, v: str):
        self.editing_name = v

    @rx.event
    def set_editing_quantity(self, v: str):
        try:
            self.editing_quantity = max(0, int(v or 0))
        except (TypeError, ValueError):
            self.editing_quantity = 0

    @rx.event
    def set_editing_category(self, v: str):
        self.editing_category = v

    @rx.event
    def set_editing_for_sale(self, v: bool):
        self.editing_for_sale = v

    @rx.event
    def set_editing_value(self, v: str):
        try:
            self.editing_value = max(0.0, float(v or 0))
        except (TypeError, ValueError):
            self.editing_value = 0.0

    @rx.event
    def set_editing_room(self, v: str):
        self.editing_room = v

    @rx.event
    def set_editing_purchase_date(self, v: str):
        self.editing_purchase_date = v

    @rx.event
    def set_editing_purchase_price(self, v: str):
        try:
            self.editing_purchase_price = max(0.0, float(v or 0))
        except (TypeError, ValueError):
            self.editing_purchase_price = 0.0

    @rx.event
    def set_editing_purchase_store(self, v: str):
        self.editing_purchase_store = v

    @rx.event
    def set_editing_return_until(self, v: str):
        self.editing_return_until = v

    @rx.event
    def set_editing_warranty_until(self, v: str):
        self.editing_warranty_until = v

    @rx.event
    async def save_edit(self):
        if not await _require_write(self, "inventory"):
            return
        name = self.editing_name.strip()
        if not name:
            self.error = "Name can't be empty."
            return
        # Detect a destructive room change *before* writing. The room
        # lives on the photo, so changing it moves every item that
        # shares the same photo_id. If >1 item is affected, surface a
        # confirm dialog and bail; the user re-triggers via
        # confirm_room_change.
        new_room = self.editing_room.strip()
        if (
            new_room
            and new_room != self.editing_initial_room
            and self.editing_photo_id
        ):
            try:
                shared = inv_db.items_for_photo(int(self.editing_photo_id)) or []
            except Exception:
                shared = []
            n = len([i for i in shared if not i.get("deleted_at")])
            if n > 1:
                self.pending_room_change_count = int(n)
                self.pending_room_change_new_room = new_room
                return
        await self._apply_save()

    async def _apply_save(self):
        name = self.editing_name.strip()
        inv_db.update_item(
            self.editing_id,
            name,
            int(self.editing_quantity),
            self.editing_category,
            for_sale=self.editing_for_sale,
            estimated_value=(
                self.editing_value if self.editing_value > 0 else None
            ),
        )
        # Room is stored on the photo; updating moves all items from that photo.
        new_room = self.editing_room.strip()
        if (
            new_room
            and new_room != self.editing_initial_room
            and self.editing_photo_id
        ):
            inv_db.update_photo_room(self.editing_photo_id, new_room)
        # Purchase / warranty subsection — only call helpers when the user
        # actually filled in something so we don't spam history with empty
        # writes on every save.
        try:
            if (
                self.editing_purchase_date
                or self.editing_purchase_price
                or self.editing_purchase_store
            ):
                inv_db.set_purchase(
                    self.editing_id,
                    purchase_date=self.editing_purchase_date or None,
                    price=(
                        self.editing_purchase_price
                        if self.editing_purchase_price > 0
                        else None
                    ),
                    store=self.editing_purchase_store or None,
                    return_until=self.editing_return_until or None,
                )
            if self.editing_return_until or self.editing_warranty_until:
                inv_db.set_warranty(
                    self.editing_id,
                    return_until=self.editing_return_until or None,
                    warranty_until=self.editing_warranty_until or None,
                )
        except Exception:
            pass
        self.editing_id = 0
        self.error = ""
        self.pending_room_change_count = 0
        self.pending_room_change_new_room = ""
        # Refresh both potential consumer views.
        search = await self.get_state(InventorySearchState)
        if search.query:
            search._refresh()
        browse = await self.get_state(InventoryBrowseState)
        browse._refresh()

    @rx.event
    async def confirm_room_change(self):
        """User clicked 'Move all N items' on the confirm dialog."""
        await self._apply_save()

    @rx.event
    def cancel_room_change(self):
        """User clicked 'Cancel' — keep the dialog open, revert room."""
        self.editing_room = self.editing_initial_room
        self.pending_room_change_count = 0
        self.pending_room_change_new_room = ""


# ---- Calendar (cross-module agenda) ------------------------------------------
class CalendarEvent(TypedDict, total=False):
    kind: str        # "task" | "meal" | "appointment"
    title: str
    detail: str
    time: str
    icon: str
    color: str
    completed: bool


class CalendarCell(TypedDict, total=False):
    date_iso: str
    day_num: int
    weekday_label: str       # e.g. "Mon May 11"
    is_current_month: bool
    is_today: bool
    is_weekend: bool
    events: list[CalendarEvent]
    event_count: int


class CalendarState(rx.State):
    """Month-grid calendar pulling from tasks, meals, and appointments.

    On desktop it renders as a 7-column month grid. On mobile it renders the
    current month's days as a vertical list of cards. Both views use the
    same underlying data; CSS switches between them via breakpoints.
    """

    current_year: int = 0
    current_month: int = 0  # 1..12
    month_label: str = ""
    weekday_labels: list[str] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    grid_cells: list[CalendarCell] = []     # exactly 42 (6 weeks × 7 days)
    mobile_days: list[CalendarCell] = []    # current-month days only

    @rx.event
    async def on_load(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        chores_db.init_db()
        meals_db.init_db()
        appt_db.init_db()
        if not self.current_year:
            today = date.today()
            self.current_year = today.year
            self.current_month = today.month
        self._refresh()

    @rx.event
    def prev_month(self):
        if self.current_month <= 1:
            self.current_year -= 1
            self.current_month = 12
        else:
            self.current_month -= 1
        self._refresh()

    @rx.event
    def next_month(self):
        if self.current_month >= 12:
            self.current_year += 1
            self.current_month = 1
        else:
            self.current_month += 1
        self._refresh()

    @rx.event
    def go_to_today(self):
        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self._refresh()

    def _collect_events_in_range(
        self, start: date, end: date
    ) -> dict[str, list[CalendarEvent]]:
        out: dict[str, list[CalendarEvent]] = {}

        def _add(d_iso: str, ev: CalendarEvent) -> None:
            out.setdefault(d_iso, []).append(ev)

        for t in chores_db.list_tasks(include_completed=True):
            due = (t.get("due_date") or "").strip()
            if not due:
                continue
            try:
                d = datetime.strptime(due, "%Y-%m-%d").date()
            except ValueError:
                continue
            if start <= d <= end:
                _add(
                    d.isoformat(),
                    {
                        "kind": "task",
                        "title": t["title"],
                        "detail": t.get("assignee_name") or "Unassigned",
                        "time": "",
                        "icon": "square-check-big",
                        "color": "blue",
                        "completed": bool(t.get("completed")),
                    },
                )

        for m in meals_db.list_meals(upcoming_only=False):
            md = (m.get("meal_date") or "").strip()
            if not md:
                continue
            try:
                d = datetime.strptime(md, "%Y-%m-%d").date()
            except ValueError:
                continue
            if start <= d <= end:
                _add(
                    d.isoformat(),
                    {
                        "kind": "meal",
                        "title": m["name"],
                        "detail": m.get("meal_type") or "",
                        "time": "",
                        "icon": "utensils",
                        "color": "orange",
                        "completed": False,
                    },
                )

        for a in appt_db.list_appointments(upcoming_only=False):
            ad_raw = a.get("appointment_at") or ""
            try:
                adt = datetime.strptime(ad_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            d = adt.date()
            if start <= d <= end:
                _add(
                    d.isoformat(),
                    {
                        "kind": "appointment",
                        "title": a["title"],
                        "detail": a.get("location") or "",
                        "time": adt.strftime("%H:%M"),
                        "icon": "calendar",
                        "color": "violet",
                        "completed": False,
                    },
                )
        return out

    def _refresh(self):
        import calendar as _cal

        today = date.today()
        year, month = self.current_year, self.current_month

        # Set the human-readable header label.
        self.month_label = date(year, month, 1).strftime("%B %Y")

        # Build a 6-week grid starting on Sunday containing the month.
        cal = _cal.Calendar(firstweekday=6)  # 6 = Sunday
        dates = list(cal.itermonthdates(year, month))
        # itermonthdates can return 28-42 entries depending on the month; pad
        # to exactly 42 by appending trailing days.
        if dates:
            while len(dates) < 42:
                dates.append(dates[-1] + timedelta(days=1))
            dates = dates[:42]

        events_by_date = self._collect_events_in_range(dates[0], dates[-1])

        grid: list[CalendarCell] = []
        mobile: list[CalendarCell] = []
        for d in dates:
            iso = d.isoformat()
            evs = sorted(
                events_by_date.get(iso, []),
                key=lambda e: (e.get("time") or "zz", e.get("title") or ""),
            )
            cell: CalendarCell = {
                "date_iso": iso,
                "day_num": d.day,
                "weekday_label": d.strftime("%A %b %d"),
                "is_current_month": (d.month == month),
                "is_today": (d == today),
                "is_weekend": d.weekday() >= 5,
                "events": evs,
                "event_count": len(evs),
            }
            grid.append(cell)
            if cell["is_current_month"]:
                mobile.append(cell)

        self.grid_cells = grid
        self.mobile_days = mobile


# ---- JARVIS Omnibox --------------------------------------------------------
class OmniboxState(rx.State):
    """Floating omnibox visible on every authed page. Pushes the query
    through assistant_chat.turn (same as AssistantState.send), captures
    the trace into last_actions, then pops a result popover.

    The trace entries are kept as plain list[dict[str, Any]] to dodge the
    Reflex 0.9 frontend crash that happens when a state var is typed as
    list[CustomTypedDict] ('d is not a function').
    """

    query: str = ""
    pending: bool = False
    last_query: str = ""          # what the user actually typed/sent
    last_response: str = ""
    last_actions: list[dict[str, Any]] = []
    popover_open: bool = False

    @rx.var
    def is_visible(self) -> bool:
        """Hidden on /login and /share-handoff."""
        try:
            path = self.router.page.path or ""
        except Exception:
            path = ""
        return path not in ("/login", "/share-handoff")

    @rx.event
    def set_query(self, value: str):
        self.query = value

    @rx.event
    def close_popover(self):
        self.popover_open = False

    @rx.event
    def open_popover(self):
        if self.last_response or self.last_actions:
            self.popover_open = True

    @rx.event
    async def continue_in_chat(self):
        """Carry the omnibox's last exchange into the chat transcript,
        close the popover, and navigate to /chat. Without this, the
        chat page opens with whatever state was already there — the
        user's question and JARVIS's reply from the omnibox would be
        invisible and a follow-up question would land without context."""
        if not (self.last_query or self.last_response):
            self.popover_open = False
            return rx.redirect("/chat")

        asst = await self.get_state(AssistantState)

        # Build transcript turns the same shape the chat page already
        # renders. _short_json'd actions become tool-call chip rows.
        new_turns: list[dict[str, Any]] = []
        if self.last_query:
            new_turns.append({"kind": "user", "text": self.last_query})
        for a in self.last_actions or []:
            new_turns.append({
                "kind": "tool_call",
                "name": a.get("name", ""),
                "args_json": a.get("args_json", ""),
                "text": "",
            })
        if self.last_response:
            new_turns.append({"kind": "assistant", "text": self.last_response})

        asst.transcript = (asst.transcript or []) + new_turns
        # Mirror into wire_messages so the next LLM turn has the
        # context. We send text-only (tool results don't replay).
        asst.wire_messages = (asst.wire_messages or []) + [
            m for m in [
                {"role": "user", "content": self.last_query}
                    if self.last_query else None,
                {"role": "assistant", "content": self.last_response}
                    if self.last_response else None,
            ] if m
        ]

        # Clear the omnibox state so the popover doesn't reopen and the
        # next question starts fresh.
        self.last_query = ""
        self.last_response = ""
        self.last_actions = []
        self.popover_open = False
        # Close the mobile drawer if it's open; otherwise it stays
        # over the new /chat view.
        ui = await self.get_state(UIState)
        ui.sidebar_open = False
        return rx.redirect("/chat")

    @rx.event
    async def submit(self):
        text = (self.query or "").strip()
        if not text or self.pending:
            return

        # If we're on /chat already, route through AssistantState so
        # the message + reply land in the visible transcript instead
        # of the omnibox popover. The popover would be redundant — the
        # user is staring at the conversation.
        try:
            path = self.router.url.pathname  # Reflex 0.9 new-style
        except Exception:
            try:
                path = self.router.page.path  # legacy fallback
            except Exception:
                path = ""
        if path == "/chat":
            asst = await self.get_state(AssistantState)
            asst.input_text = text
            self.query = ""
            self.popover_open = False
            # AssistantState.send is an async generator; forward every
            # yielded event so the transcript updates progressively.
            async for ev in asst.send():
                yield ev
            return

        self.pending = True
        self.popover_open = False
        yield

        auth = await self.get_state(AuthState)
        user_name = auth.current_user_name or None

        try:
            trace = await asyncio.to_thread(
                assistant_chat.turn,
                [{"role": "user", "content": text}],
                user_name,
            )
        except Exception:
            import traceback, sys
            traceback.print_exc(file=sys.stderr)
            self.last_response = (
                "Something went sideways with the LLM. Check the "
                "server log and Settings → API."
            )
            self.last_actions = []
            self.popover_open = True
            self.pending = False
            return

        actions: list[dict[str, Any]] = []
        final_text = ""
        for entry in trace:
            kind = entry.get("kind")
            if kind == "tool_call":
                actions.append({
                    "name": entry.get("name") or "",
                    "args_json": _short_json(entry.get("args") or {}),
                })
            elif kind == "assistant":
                t = entry.get("text") or ""
                if t:
                    final_text = t

        self.last_actions = actions
        self.last_response = final_text or "(no reply)"
        self.last_query = text  # preserved for "Continue in chat" handoff
        self.query = ""
        self.pending = False
        self.popover_open = True
