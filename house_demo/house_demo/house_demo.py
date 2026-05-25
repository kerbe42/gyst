"""Reflex app entry point for the House App demo.

Run from this directory:
    reflex run --env prod

Both frontend and backend on port 3001 (configured in rxconfig.py).
"""

from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

import reflex as rx
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, Response

from inventory import db as inv_db
from chores import db as chores_db
from notifications import db as push_db

import config


# ---- Cookie-based auth gate for static endpoints -----------------------------
# The Reflex client persists the session in a cookie named "house_session"
# (see AuthState.session_token). The photo-serving routes below are plain
# Starlette routes, so they don't get the Reflex auth pipeline automatically —
# we have to validate the cookie ourselves on each request.
_SESSION_COOKIE_NAME = (
    "house_session_" + os.environ["GYST_ENV"]
    if os.environ.get("GYST_ENV")
    else "house_session"
)


def _user_for_request(request: Request):
    token = request.cookies.get(_SESSION_COOKIE_NAME)
    if not token:
        return None
    try:
        return chores_db.validate_session(token)
    except Exception:
        return None


def _require_request_auth(request: Request, *, read: str | None = None):
    """Raise HTTPException(401/403) if the request can't access the resource.
    Logs every photo-route hit so we can debug client-side fetch failures."""
    import sys as _sys

    cookie_present = _SESSION_COOKIE_NAME in request.cookies
    user = _user_for_request(request)
    print(
        f"[photo-auth] path={request.url.path} "
        f"cookie_present={cookie_present} "
        f"user={user.get('name') if user else None} "
        f"read={read} "
        f"ua={request.headers.get('user-agent', '?')[:60]}",
        file=_sys.stderr,
    )
    _sys.stderr.flush()
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if read == "inventory" and not user.get("can_read_inventory"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if read == "chores" and not user.get("can_read_chores"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


_PRIVATE_CACHE = {
    "Cache-Control": "private, max-age=3600",
    # Stop browsers from MIME-sniffing photo responses. Even though we
    # always set Content-Type: image/jpeg, this is cheap defense-in-depth
    # if a malformed-but-PIL-accepted payload ever slipped through.
    "X-Content-Type-Options": "nosniff",
}


# Cap inbound photo uploads at 25 MB. Modern phone photos are 2–5 MB;
# leaves headroom for HEIC/ProRAW while preventing an authenticated
# user (or a CSRF-shaped POST) from OOMing the server with a huge body.
# CWE-770 (Allocation of Resources Without Limits or Throttling).
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _reject_oversize_upload(
    request: Request, max_bytes: int = _MAX_UPLOAD_BYTES
) -> None:
    """Raise HTTPException(413) if the request's Content-Length header
    declares a body larger than ``max_bytes``. Header is a hint, not a
    guarantee — callers should also use _enforce_size_after_read()
    once the body is in hand."""
    cl = request.headers.get("content-length")
    if cl is None:
        return
    try:
        n = int(cl)
    except ValueError:
        return
    if n > max_bytes:
        raise HTTPException(status_code=413, detail="Upload too large")


def _enforce_size_after_read(
    data: bytes, max_bytes: int = _MAX_UPLOAD_BYTES
) -> None:
    """Belt-and-suspenders: after reading the body, verify the actual
    byte count is within the cap (the Content-Length header may have
    been absent or wrong)."""
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="Upload too large")


# Origin/Referer allow-list for cookie-authed POST endpoints. The session
# cookie is SameSite=Lax, which already blocks most cross-site form POSTs
# in modern browsers — but the Lax exemption for top-level navigations
# can let through a `<form method=POST>` submission from a malicious page,
# and any future tightening or browser bug would expose us. This is
# explicit defense in depth. See CWE-352 (CSRF).
_ALLOWED_ORIGINS = frozenset({
    "https://gyst.local",
    "https://gyst.local:443",
    "https://gyst.local:8443",   # dev
    "http://localhost",                # local curl / loopback
    "http://127.0.0.1",
})


def _check_csrf_origin(request: Request) -> None:
    """Reject the request if its Origin (or, if absent, Referer) header
    points outside our allow-list. Skips the check when neither header
    is present — some legitimate clients (curl scripts, the JARVIS
    proactive timer hitting localhost) don't send either.

    DO NOT call this on `/share-target`: that endpoint receives POSTs
    from the OS share sheet, where the source origin is the sharing
    app, not us. Web Share Target is its own trust model — the user's
    deliberate share action is the auth signal."""
    from urllib.parse import urlsplit

    origin = (request.headers.get("origin") or "").strip()
    referer = (request.headers.get("referer") or "").strip()
    src = origin or referer
    if not src:
        # No header — could be a non-browser client. Cookie auth still
        # gates the endpoint; SameSite=Lax + no preflight-via-fetch
        # blocks the cross-origin browser case. Don't reject.
        return
    try:
        parsed = urlsplit(src)
        # netloc carries host[:port]; build canonical scheme://host[:port].
        src_origin = f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid request origin")
    if src_origin not in _ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403, detail="Cross-origin request rejected"
        )


# Per-user rate limit for endpoints that trigger paid LLM calls
# (recognition pipeline, receipt OCR, etc.). An attacker who steals a
# session cookie — or just a buggy client retrying in a loop — could
# otherwise run up the Anthropic/OpenAI bill. Sliding 60-min window,
# 60 requests; in-memory (lossy across restarts is fine for a homelab).
# CWE-799 (Improper Control of Interaction Frequency).
import threading as _threading
import time as _time

_LLM_RATE_LIMIT = 60
_LLM_WINDOW_SEC = 3600
_llm_call_log: dict[int, list[float]] = {}
_llm_lock = _threading.Lock()


def _check_llm_rate_limit(user_id: int) -> None:
    """Raise HTTPException(429) if this user has used more than
    ``_LLM_RATE_LIMIT`` LLM calls in the last ``_LLM_WINDOW_SEC`` seconds.
    Otherwise record the call and return."""
    now = _time.time()
    cutoff = now - _LLM_WINDOW_SEC
    with _llm_lock:
        calls = [t for t in _llm_call_log.get(user_id, []) if t > cutoff]
        if len(calls) >= _LLM_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded — try again later.",
            )
        calls.append(now)
        _llm_call_log[user_id] = calls


def _capture_response(request: Request, body: dict, status: int = 200):
    """Return either JSONResponse (for fetch callers) or a 303 redirect
    to ``/inventory/capture?recent=<photo_id>`` (for HTML form submits).

    A native HTML form-submit hands the upload to the browser, which
    streams the file from disk without JS having to decode/buffer it —
    on memory-tight Android WebView (PWA) that's the difference between
    "works" and "OS kills the process for memory". The cost is that we
    no longer have JS to render the response, so on success we 303
    back to the capture page with ``?recent=<id>``; ``on_load`` reads
    that param and hydrates the summary list.

    Fetch callers (older tests, /api/scan-product-style clients) still
    get JSON when they pass ``Accept: application/json``."""
    from starlette.responses import JSONResponse, RedirectResponse
    accept = (request.headers.get("accept") or "").lower()
    wants_json = "application/json" in accept
    # 4xx/5xx always go back as JSON; redirecting on error would hide
    # the failure and bounce the user into a fresh page that doesn't
    # know anything went wrong.
    if wants_json or status >= 400:
        return JSONResponse(body, status_code=status)
    pid = int(body.get("photo_id") or 0)
    target = "/inventory/capture"
    if pid > 0:
        target += f"?recent={pid}"
    return RedirectResponse(url=target, status_code=303)


def _prune_old_shared_photos(max_age_sec: int = 3600) -> int:
    """Delete files in ``PHOTOS_DIR/shared`` older than ``max_age_sec``.

    The PWA share-target stages each shared photo to disk and lets the
    capture page pick it up via cookie within 5 minutes. If the user
    bounces away, the staging file is orphaned. We sweep on every new
    share so a busy user keeps the directory drained; in the
    pathological case (zero shares for a long time) the directory just
    holds onto its last-shared file until the next share."""
    shared_dir = config.PHOTOS_DIR / "shared"
    if not shared_dir.is_dir():
        return 0
    cutoff = _time.time() - max_age_sec
    pruned = 0
    for f in shared_dir.iterdir():
        try:
            if not f.is_file():
                continue
            if f.stat().st_mtime < cutoff:
                f.unlink()
                pruned += 1
        except OSError:
            pass
    return pruned
from house_demo.pages import (
    announcements_page,
    chat_page,
    appointments_add_page,
    appointments_page,
    calendar_page,
    chores_add_page,
    chores_tasks_page,
    groceries_add_page,
    groceries_page,
    home_page,
    inventory_browse_page,
    help_page,
    inventory_capture_page,
    inventory_food_page,
    inventory_for_sale_page,
    inventory_search_page,
    inventory_trash_page,
    item_detail_page,
    login_page,
    meals_add_page,
    meals_page,
    notes_page,
    settings_page,
    share_handoff_page,
)
from house_demo.states import (
    AnnouncementsState,
    AssistantState,
    AppointmentsState,
    CalendarState,
    ChoresAddState,
    ChoresTasksState,
    GroceriesState,
    HomeState,
    InventoryBrowseState,
    InventoryCaptureState,
    InventoryFoodState,
    InventoryForSaleState,
    InventorySearchState,
    InventoryTrashState,
    ItemDetailState,
    MealsState,
    NotesState,
    SettingsState,
    ShareHandoffState,
)

app = rx.App(
    stylesheets=["/styles.css"],
    head_components=[
        # Global JS shim — adds capture="environment" to image file inputs
        # so tapping the upload zone on mobile opens the camera directly.
        rx.el.script(src="/camera-capture.js?v=20260513c"),
        # In-page camera (getUserMedia + canvas) — primary capture path
        # on memory-tight Android PWAs where the system camera intent
        # OOMs the WebView. Defer so it doesn't block first paint.
        rx.el.script(src="/gyst-camera.js?v=20260513k", defer=True),
        # PWA: manifest + service worker registration. Lets Android Chrome
        # offer "Install app" so GYST runs full-screen from the home screen.
        rx.el.link(rel="manifest", href="/manifest.webmanifest"),
        rx.el.meta(name="theme-color", content="#3b3bf5"),
        rx.el.meta(name="apple-mobile-web-app-capable", content="yes"),
        rx.el.meta(
            name="apple-mobile-web-app-status-bar-style",
            content="black-translucent",
        ),
        rx.el.meta(name="apple-mobile-web-app-title", content="GYST"),
        rx.el.link(
            rel="apple-touch-icon", href="/icons/icon-192.png"
        ),
        rx.el.script(src="/pwa-register.js?v=20260513e", defer=True),
        # Barcode scanner — used by Add items to read UPC/EAN codes via the
        # camera and look the product up against Open Food Facts.
        rx.el.script(src="/barcode.js?v=20260514h", defer=True),
        # Defines window._gystAddBarcode — must load via <script src>
        # because React refuses to execute inline <script> content.
        rx.el.script(src="/scan-product.js?v=20260513w", defer=True),
        # Voice input — used by Add items to dictate a product name.
        rx.el.script(src="/voice.js", defer=True),
        # Watches the undo snack's data-seq attribute and auto-dismisses
        # 1.8s after each fresh arm.
        rx.el.script(src="/undo-snack.js", defer=True),
    ],
)

app.add_page(login_page, route="/login", title="Sign in")
app.add_page(home_page, route="/", title="GYST", on_load=HomeState.on_load)
app.add_page(
    chat_page,
    route="/chat",
    title="JARVIS",
    on_load=AssistantState.on_load,
)
app.add_page(
    inventory_capture_page,
    route="/inventory/capture",
    title="Add items",
    on_load=InventoryCaptureState.on_load,
)
app.add_page(
    share_handoff_page,
    route="/share-handoff",
    title="Share to GYST",
    on_load=ShareHandoffState.on_load,
)
app.add_page(
    inventory_search_page,
    route="/inventory/search",
    title="Search",
    on_load=InventorySearchState.on_load,
)
app.add_page(
    inventory_browse_page,
    route="/inventory/browse",
    title="Browse",
    on_load=InventoryBrowseState.on_load,
)
app.add_page(
    inventory_for_sale_page,
    route="/inventory/for-sale",
    title="For sale",
    on_load=InventoryForSaleState.on_load,
)
app.add_page(
    inventory_food_page,
    route="/inventory/food",
    title="Food inventory",
    on_load=InventoryFoodState.on_load,
)
app.add_page(
    inventory_trash_page,
    route="/inventory/trash",
    title="Trash",
    on_load=InventoryTrashState.on_load,
)
app.add_page(
    item_detail_page,
    route="/inventory/item/[id]",
    title="Item details",
    on_load=ItemDetailState.on_load,
)
app.add_page(
    chores_tasks_page,
    route="/chores/tasks",
    title="Tasks",
    on_load=ChoresTasksState.on_load,
)
app.add_page(
    chores_add_page,
    route="/chores/add",
    title="Add task",
    on_load=ChoresAddState.on_load,
)
app.add_page(
    settings_page,
    route="/settings",
    title="Settings",
    on_load=[SettingsState.on_load, AnnouncementsState.on_load],
)
app.add_page(
    announcements_page,
    route="/announcements",
    title="Announcements",
    on_load=AnnouncementsState.on_load,
)
app.add_page(
    calendar_page,
    route="/calendar",
    title="Calendar",
    on_load=CalendarState.on_load,
)
app.add_page(
    groceries_page,
    route="/groceries",
    title="Shopping list",
    on_load=GroceriesState.on_load,
)
app.add_page(
    groceries_add_page,
    route="/groceries/add",
    title="Add to shopping list",
    on_load=GroceriesState.on_load,
)
app.add_page(
    meals_page,
    route="/meals",
    title="Meal plan",
    on_load=MealsState.on_load,
)
app.add_page(
    meals_add_page,
    route="/meals/add",
    title="Plan a meal",
    on_load=MealsState.on_load,
)
app.add_page(
    notes_page,
    route="/notes",
    title="Notes",
    on_load=NotesState.on_load,
)
app.add_page(
    appointments_page,
    route="/appointments",
    title="Schedule",
    on_load=AppointmentsState.on_load,
)
app.add_page(
    appointments_add_page,
    route="/appointments/add",
    title="New appointment",
    on_load=AppointmentsState.on_load,
)
app.add_page(
    help_page,
    route="/help",
    title="Help",
)


# ---- Photo serving -----------------------------------------------------------
# Serve files from data/photos/ over the same backend port. The frontend
# references these as /photo/<filename>.
#
# Reflex 0.9 uses Starlette (not FastAPI) under the hood. The underlying app
# is on `app._api`; routes are registered with Starlette's `add_route`.

# ---- FX + product-image helpers (used by /api/scan-product) ------------------
# CAD conversion for prices from US-source databases (UPCitemdb is USD).
# Frankfurter is a free ECB-backed FX API (no key, ~daily updates). We
# cache the rate in-process for 24h and fall back to a hardcoded sane
# value if the API is down — better to over/underestimate slightly than
# to crash the scan flow.
_FX_CACHE: dict[str, dict[str, float]] = {}
_FX_FALLBACK = 1.37  # rough mid-2026 USD -> CAD; sanity fallback only.
_PRODUCT_IMAGE_HOSTS = frozenset({
    "images.upcitemdb.com",
    "images.openfoodfacts.org",
    "static.openfoodfacts.org",
    "world.openfoodfacts.org",
    "covers.openlibrary.org",
})


def _usd_to_user_currency(usd: float) -> float:
    """Convert USD to the user's selected currency (Settings ->
    Appearance, default CAD). Caches the rate per (target_currency)
    for 24h. Falls back to ``_FX_FALLBACK`` if the upstream is down.

    The cache key is the target code so a user toggling between
    currencies doesn't bust each other's cached value."""
    import urllib.request, json as _json, time as _t, urllib.parse
    from app_settings import db as _settings_db
    target = _settings_db.get_currency() or "CAD"
    if target == "USD":
        return round(float(usd), 2)
    key = target.upper()
    now = _t.time()
    entry = _FX_CACHE.get(key)
    if (not entry) or ((now - entry.get("fetched_at", 0)) > 86400):
        try:
            url = ("https://api.frankfurter.dev/v1/latest?from=USD&to="
                   + urllib.parse.quote(key))
            req = urllib.request.Request(url, headers={"User-Agent": "gyst-scan"})
            with urllib.request.urlopen(req, timeout=4) as r:
                data = _json.loads(r.read())
                rate = float(data["rates"][key])
                if 0.01 < rate < 1e5:  # broad sanity bounds (incl. JPY etc.)
                    _FX_CACHE[key] = {"rate": rate, "fetched_at": now}
        except Exception:
            pass
    rate = (_FX_CACHE.get(key) or {}).get("rate") or _FX_FALLBACK
    return round(float(usd) * rate, 2)


# Backwards-compat shim: old call sites still use _usd_to_cad.
def _usd_to_cad(usd: float) -> float:
    return _usd_to_user_currency(usd)


def _fetch_product_image(url: str, dest: Path) -> bool:
    """SSRF-guarded fetch of a product image to ``dest``. Returns True
    on success. Hostname must be in ``_PRODUCT_IMAGE_HOSTS`` (UPCitemdb,
    OpenFoodFacts, Open Library covers). Caps at 4 MB. Requires HTTPS
    and image/* Content-Type."""
    import urllib.request, urllib.parse
    if not url or not isinstance(url, str):
        return False
    if not url.startswith("https://"):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if (parsed.hostname or "").lower() not in _PRODUCT_IMAGE_HOSTS:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gyst-scan"})
        with urllib.request.urlopen(req, timeout=6) as r:
            ctype = (r.headers.get("Content-Type", "") or "").lower()
            if not ctype.startswith("image/"):
                return False
            data = r.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                return False
            if not data:
                return False
    except Exception:
        return False
    try:
        from house_demo.states import _save_oriented_jpeg
        _save_oriented_jpeg(data, dest)
        return True
    except Exception:
        try:
            dest.write_bytes(data)
            return True
        except Exception:
            return False

async def serve_photo(request: Request):
    _require_request_auth(request, read="inventory")
    filename = request.path_params.get("filename", "")
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = config.PHOTOS_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(
        str(path), media_type="image/jpeg", headers=_PRIVATE_CACHE,
    )


def _crop_to_bytes(photo_path: Path, boxes: list) -> bytes:
    """Open the photo, EXIF-orient, crop to the union of `boxes` (with a 40%
    padding band around the item so there's visible context), and return JPEG
    bytes. Pure sync; meant for asyncio.to_thread."""
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")

    valid = [b for b in (boxes or []) if isinstance(b, (list, tuple)) and len(b) >= 4]
    if valid:
        min_x = min(b[0] for b in valid)
        min_y = min(b[1] for b in valid)
        max_x = max(b[2] for b in valid)
        max_y = max(b[3] for b in valid)
        w = max(1.0, max_x - min_x)
        h = max(1.0, max_y - min_y)
        pad_x = w * 0.4
        pad_y = h * 0.4
        img = img.crop(
            (
                max(0, int(min_x - pad_x)),
                max(0, int(min_y - pad_y)),
                min(img.width, int(max_x + pad_x)),
                min(img.height, int(max_y + pad_y)),
            )
        )

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


async def serve_item_crop(request: Request):
    """Return a JPEG cropped to a specific item's bounding box."""
    _require_request_auth(request, read="inventory")
    raw = request.path_params.get("item_id", "")
    try:
        item_id = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid item_id")

    item = inv_db.get_item_with_photo(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    photo_path = Path(item.get("photo_path") or "")
    if not photo_path.exists() or not photo_path.is_file():
        raise HTTPException(status_code=404, detail="Photo missing")

    image_bytes = await asyncio.to_thread(
        _crop_to_bytes, photo_path, item.get("boxes") or []
    )
    return Response(
        content=image_bytes, media_type="image/jpeg", headers=_PRIVATE_CACHE,
    )


async def serve_chore_photo(request: Request):
    """Serve chore proof-of-completion photos from data/chore_photos/."""
    _require_request_auth(request, read="chores")
    filename = request.path_params.get("filename", "")
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = config.CHORE_PHOTOS_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(
        str(path), media_type="image/jpeg", headers=_PRIVATE_CACHE,
    )


async def push_vapid_public_key(request: Request):
    """Public VAPID key — the browser passes it to PushManager.subscribe() as
    applicationServerKey. Safe to serve unauthenticated; it's public by design."""
    from starlette.responses import JSONResponse

    vapid = push_db.ensure_vapid_keys()
    return JSONResponse({"public_key": vapid["public"]})


async def push_subscribe(request: Request):
    """Register a Web Push subscription for the current user.

    The push endpoint URL is provided by the browser's PushManager, but
    nothing on the wire forces it to be a real push service — a malicious
    client could submit `endpoint=http://10.0.0.1/admin/...` and turn the
    server into an SSRF cannon when send_to_user() fires later. So we
    require HTTPS, a known push-service hostname, and reject IPs.
    """
    from starlette.responses import JSONResponse
    from urllib.parse import urlparse

    _check_csrf_origin(request)
    user = _require_request_auth(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    endpoint = (payload.get("endpoint") or "").strip()
    keys = payload.get("keys") or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Missing fields")

    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Endpoint must be HTTPS")
    host = parsed.hostname.lower()
    # Known major push services. Browsers don't currently issue endpoints
    # outside this set; expand if Firefox/Edge introduce new ones.
    _ALLOWED_PUSH_HOSTS = (
        "fcm.googleapis.com",       # Chrome / Edge / Brave (Android, desktop)
        "android.googleapis.com",   # legacy Chrome
        "updates.push.services.mozilla.com",   # Firefox
        "web.push.apple.com",       # Safari (macOS 13+, iOS 16.4+)
        "wns2-*.notify.windows.com",
    )
    def _host_ok(h: str) -> bool:
        for pat in _ALLOWED_PUSH_HOSTS:
            if pat.startswith("*."):
                if h.endswith(pat[1:]):
                    return True
            elif "*" in pat:
                # crude glob: prefix-*-suffix
                import fnmatch
                if fnmatch.fnmatch(h, pat):
                    return True
            elif h == pat:
                return True
        return False
    if not _host_ok(host):
        raise HTTPException(
            status_code=400,
            detail=f"Push endpoint host not on the allow-list: {host}",
        )

    push_db.upsert_subscription(
        user_id=int(user["id"]),
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=request.headers.get("user-agent", "")[:200],
    )
    return JSONResponse({"ok": True})


async def push_unsubscribe(request: Request):
    """Drop the supplied endpoint from this user's subscriptions."""
    from starlette.responses import JSONResponse
    _check_csrf_origin(request)
    user = _require_request_auth(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    endpoint = (payload.get("endpoint") or "").strip()
    if not endpoint:
        # If browser doesn't have a subscription, nuke all for this user.
        push_db.delete_subscriptions_for_user(int(user["id"]))
    else:
        push_db.delete_subscription_by_endpoint(endpoint)
    return JSONResponse({"ok": True})


async def api_capture_upload(request: Request):
    """Direct photo upload that bypasses Reflex's rx.upload entirely.
    The camera/gallery buttons in the capture page POST their picked file
    here as multipart/form-data; we save the photo and run the full
    recognition pipeline server-side, then return JSON the JS uses to
    navigate to /inventory/capture?recent=<photo_id> so the on_load can
    surface the saved items in the normal summary UI.

    This exists because Chrome's React-onChange diffing made the in-page
    DataTransfer handoff to rx.upload unreliable — files were picked but
    the on_drop handler never fired."""
    from starlette.responses import JSONResponse
    import sys as _sys
    import secrets as _sec
    import asyncio as _asyncio
    from datetime import datetime as _dt, date as _date, timedelta as _td
    from pathlib import Path as _Path

    from inventory import recognize as _recognize

    _check_csrf_origin(request)
    user = _require_request_auth(request, read="inventory")
    if not user.get("can_write_inventory"):
        raise HTTPException(status_code=403, detail="Forbidden")
    _check_llm_rate_limit(int(user["id"]))
    _reject_oversize_upload(request)

    form = await request.form()
    file_ul = form.get("file")
    if file_ul is None or not hasattr(file_ul, "read"):
        raise HTTPException(status_code=400, detail="Missing file")
    room = (form.get("room") or "default").strip().lower()
    mode = (form.get("mode") or "objects").strip().lower()
    if mode not in ("objects", "receipt"):
        mode = "objects"

    inv_db.init_db()
    allowed = {r.lower() for r in inv_db.list_room_names()}
    allowed.add("default")
    if room not in allowed:
        room = "default"

    # Save bytes to disk (oriented JPEG).
    from house_demo.states import _save_oriented_jpeg
    data = await file_ul.read()
    _enforce_size_after_read(data)
    config.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    token = _sec.token_hex(8)
    out_path = config.PHOTOS_DIR / f"{ts}_{token}.jpg"
    await _asyncio.to_thread(_save_oriented_jpeg, data, out_path)
    photo_path = str(out_path)
    print(
        f"[api/capture-upload] user={user.get('name')} room={room} mode={mode} "
        f"bytes={len(data)} path={photo_path}",
        file=_sys.stderr,
    )

    try:
        if mode == "receipt":
            receipt = await _asyncio.to_thread(
                _recognize.identify_receipt, _Path(photo_path)
            )
            line_items = receipt.get("items") or []
            if not line_items:
                return _capture_response(request, {
                    "ok": True, "item_count": 0,
                    "message": "No line items detected.",
                    "photo_id": 0,
                })
            purchase_date = receipt.get("date") or _date.today().isoformat()
            return_until = None
            try:
                pd = _dt.strptime(purchase_date, "%Y-%m-%d").date()
                return_until = (pd + _td(days=30)).isoformat()
            except (TypeError, ValueError):
                return_until = None
            photo_id = await _asyncio.to_thread(
                inv_db.save_photo, photo_path, room
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
            new_ids = await _asyncio.to_thread(
                inv_db.save_items, photo_id, candidates,
            )
            store = (receipt.get("store") or "").strip() or None
            for nid, li in zip(new_ids, line_items):
                try:
                    inv_db.set_purchase(
                        int(nid),
                        purchase_date=purchase_date,
                        price=li.get("price"),
                        store=store,
                        return_until=return_until,
                    )
                except Exception:
                    pass
            return _capture_response(request, {
                "ok": True,
                "item_count": len(new_ids),
                "photo_id": int(photo_id),
                "mode": "receipt",
            })

        # objects mode
        identified = await _asyncio.to_thread(
            _recognize.identify_items, _Path(photo_path)
        )
        if not identified:
            return _capture_response(request, {
                "ok": True, "item_count": 0,
                "message": "Nothing recognizable in this photo.",
                "photo_id": 0,
            })

        # Bookshelf fast-path.
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
            shelf = await _asyncio.to_thread(
                _recognize.extract_book_titles_from_shelf, _Path(photo_path)
            )
            if shelf:
                photo_id = await _asyncio.to_thread(
                    inv_db.save_photo, photo_path, room
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
                new_ids = await _asyncio.to_thread(
                    inv_db.save_items, photo_id, candidates,
                )
                return _capture_response(request, {
                    "ok": True,
                    "item_count": len(new_ids),
                    "photo_id": int(photo_id),
                    "mode": "bookshelf",
                })

        labels = [it.name for it in identified]
        counts, boxes_per_label = await _asyncio.to_thread(
            _recognize.count_items, _Path(photo_path), labels
        )
        recognized = await _asyncio.to_thread(
            _recognize.refine_text_items,
            _Path(photo_path),
            identified,
            counts,
            boxes_per_label,
        )
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
        photo_id = await _asyncio.to_thread(
            inv_db.save_photo, photo_path, room
        )
        new_ids = await _asyncio.to_thread(
            inv_db.save_items, photo_id, candidates,
        )
        return _capture_response(request, {
            "ok": True,
            "item_count": len(new_ids),
            "photo_id": int(photo_id),
            "mode": "objects",
        })
    except Exception as exc:
        import traceback as _tb
        _tb.print_exc(file=_sys.stderr)
        return JSONResponse(
            {"ok": False, "error": str(exc)[:300]},
            status_code=500,
        )


async def api_scan_product(request: Request):
    """Direct-add an inventory item from a barcode scan.

    Accepts EITHER:
      - multipart/form-data with fields name, upc, room, image_url,
        est_price_usd, category, and optional file (still frame from
        the scanner); or
      - application/json with the same fields minus file (legacy /
        manual UPC entry).

    Photo resolution priority:
      1. multipart `file` (the paused video frame the user scanned) ->
         saved as oriented JPEG.
      2. `image_url` (SSRF-guarded against _PRODUCT_IMAGE_HOSTS) ->
         server fetches and saves.
      3. Fallback to `barcode://<upc>` placeholder path.

    Pricing: `est_price_usd` is converted to CAD via _usd_to_cad and
    stored as the item's estimated_value. The client computes the USD
    estimate from UPCitemdb's low/high range; OFF + Open Library don't
    return prices.
    """
    from starlette.responses import JSONResponse
    import asyncio as _asyncio, secrets as _sec
    from datetime import datetime as _dt

    _check_csrf_origin(request)
    user = _require_request_auth(request, read="inventory")
    if not user.get("can_write_inventory"):
        raise HTTPException(status_code=403, detail="Forbidden")
    _reject_oversize_upload(request)

    ctype = (request.headers.get("content-type") or "").lower()
    name = upc = room = image_url = category_hint = ""
    est_price_usd_str = ""
    file_ul = None

    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        name = (form.get("name") or "").strip()
        upc = (form.get("upc") or "").strip()
        room = (form.get("room") or "default").strip().lower()
        image_url = (form.get("image_url") or "").strip()
        est_price_usd_str = str(form.get("est_price_usd") or "").strip()
        category_hint = (form.get("category") or "").strip()
        file_ul = form.get("file")
    else:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid request body")
        name = (payload.get("name") or "").strip()
        upc = (payload.get("upc") or "").strip()
        room = (payload.get("room") or "default").strip().lower()
        image_url = (payload.get("image_url") or "").strip()
        est_price_usd_str = str(payload.get("est_price_usd") or "").strip()
        category_hint = (payload.get("category") or "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="Missing name")

    inv_db.init_db()
    allowed = {r.lower() for r in inv_db.list_room_names()}
    allowed.add("default")
    if room not in allowed:
        room = "default"

    # Pick a photo path.
    config.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    token = _sec.token_hex(8)
    out_path = config.PHOTOS_DIR / f"{ts}_{token}.jpg"
    photo_path = ""

    if file_ul is not None and hasattr(file_ul, "read"):
        try:
            data = await file_ul.read()
            _enforce_size_after_read(data)
            from house_demo.states import _save_oriented_jpeg
            await _asyncio.to_thread(_save_oriented_jpeg, data, out_path)
            photo_path = str(out_path)
        except Exception:
            photo_path = ""

    if not photo_path and image_url:
        ok = await _asyncio.to_thread(_fetch_product_image, image_url, out_path)
        if ok:
            photo_path = str(out_path)

    if not photo_path:
        photo_path = f"barcode://{upc or 'manual'}"

    photo_id = inv_db.save_photo(photo_path, room)

    # USD -> CAD conversion
    estimated_value_cad = None
    try:
        usd = float(est_price_usd_str)
        if usd > 0:
            estimated_value_cad = await _asyncio.to_thread(_usd_to_cad, usd)
    except (TypeError, ValueError):
        estimated_value_cad = None

    new_ids = inv_db.save_items(
        photo_id,
        [{
            "name": name,
            "category": category_hint or "other",
            "quantity": 1,
            "detector_count": 0,
            "boxes": [],
            "for_sale": False,
            "estimated_value": estimated_value_cad,
        }],
    )
    return JSONResponse({
        "ok": True,
        "id": new_ids[0] if new_ids else 0,
        "estimated_value_cad": estimated_value_cad,
    })


async def serve_ical(request: Request):
    """Per-user iCal calendar subscription. Authenticated by an opaque
    `?token=...` URL parameter — calendar apps (iOS Calendar, Google Cal,
    Thunderbird) don't carry cookies, so we use a token in the URL
    instead. Users mint/rotate the token from Settings → Misc."""
    from starlette.responses import Response

    token = request.query_params.get("token", "").strip()
    user = chores_db.user_by_ical_token(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")

    from appointments import db as appt_db
    from meals import db as meals_db
    from datetime import datetime as _dt

    def _ical_dt(s: str) -> str:
        """ISO 'YYYY-MM-DD HH:MM:SS' -> iCal 'YYYYMMDDTHHMMSS' (floating local)."""
        try:
            d = _dt.strptime(s, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return ""
        return d.strftime("%Y%m%dT%H%M%S")

    def _ical_date(s: str) -> str:
        try:
            d = _dt.strptime(s, "%Y-%m-%d")
        except (ValueError, TypeError):
            return ""
        return d.strftime("%Y%m%d")

    def _esc(s: str) -> str:
        if not s:
            return ""
        return (
            s.replace("\\", "\\\\")
             .replace(",", "\\,")
             .replace(";", "\\;")
             .replace("\n", "\\n")
        )

    chores_db.init_db()
    appt_db.init_db()
    meals_db.init_db()

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//GYST//EN",
        f"X-WR-CALNAME:GYST — {user['name']}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    now_stamp = _dt.now().strftime("%Y%m%dT%H%M%S")

    # ---- Tasks with due dates (all-day events) ----
    for t in chores_db.list_tasks(include_completed=False):
        due = (t.get("due_date") or "").strip()
        if not due:
            continue
        d = _ical_date(due)
        if not d:
            continue
        uid = f"task-{t['id']}@gyst"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART;VALUE=DATE:{d}",
            f"SUMMARY:{_esc('☐ ' + t['title'])}",
        ]
        if t.get("description"):
            lines.append(f"DESCRIPTION:{_esc(t['description'])}")
        if t.get("assignee_name"):
            lines.append(
                f"DESCRIPTION:{_esc('Assigned to ' + t['assignee_name'])}"
            )
        lines.append("END:VEVENT")

    # ---- Appointments (timed events, 1 hour duration) ----
    for a in appt_db.list_appointments(upcoming_only=False):
        when = _ical_dt(a.get("appointment_at") or "")
        if not when:
            continue
        uid = f"appt-{a['id']}@gyst"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART:{when}",
            # Default to 1-hour duration; we don't track end times yet.
            f"DURATION:PT1H",
            f"SUMMARY:{_esc(a['title'])}",
        ]
        if a.get("location"):
            lines.append(f"LOCATION:{_esc(a['location'])}")
        if a.get("notes"):
            lines.append(f"DESCRIPTION:{_esc(a['notes'])}")
        lines.append("END:VEVENT")

    # ---- Meals (all-day events) ----
    for m in meals_db.list_meals(upcoming_only=False):
        md = _ical_date((m.get("meal_date") or "").strip())
        if not md:
            continue
        uid = f"meal-{m['id']}@gyst"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART;VALUE=DATE:{md}",
            f"SUMMARY:{_esc('🍽 ' + m['name'])}",
        ]
        if m.get("meal_type"):
            lines.append(f"DESCRIPTION:{_esc(m['meal_type'])}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    body = "\r\n".join(lines) + "\r\n"
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "private, max-age=600"},
    )


async def share_target(request: Request):
    """PWA Web Share Target receiver.

    The browser POSTs multipart/form-data here when the user picks
    "Share to GYST" from another app. We split on whether there was an
    image attached:
      - image -> stash to PHOTOS_DIR/shared/, set a short-lived cookie
        with the absolute path, 303 redirect to /capture so the capture
        page can pick it up on_load.
      - text/url only -> 303 redirect to /share-handoff?text=... so the
        user can pick a destination (note / grocery / task).
    If the user isn't logged in, send them through /login?next=... so
    they land back here after authenticating.
    """
    from datetime import datetime
    from starlette.responses import RedirectResponse
    from urllib.parse import urlencode, quote
    import secrets as _sec

    # Auth check — but instead of 401, bounce through login.
    user = _user_for_request(request)
    if not user:
        # Preserve the share data? Hard with multipart. For now just send
        # them to login with a next hint to /. They can re-share after.
        return RedirectResponse(url="/login?next=/", status_code=303)
    if not user.get("can_read_inventory") and not user.get("can_write_inventory"):
        # No inventory access — still allow text handoff but no photo route.
        pass
    _reject_oversize_upload(request)

    try:
        form = await request.form()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid share payload")

    title = (form.get("title") or "").strip()
    text = (form.get("text") or "").strip()
    url_field = (form.get("url") or "").strip()

    # files may come as either "files" (per the manifest) or other keys.
    file_obj = None
    for key in ("files", "file", "photo"):
        candidate = form.get(key)
        if candidate is not None and hasattr(candidate, "read"):
            file_obj = candidate
            break

    if file_obj is not None:
        mimetype = (getattr(file_obj, "content_type", "") or "").lower()
        if mimetype.startswith("image/"):
            data = await file_obj.read()
            _enforce_size_after_read(data)
            if not data:
                raise HTTPException(status_code=400, detail="Empty shared file")
            shared_dir = config.PHOTOS_DIR / "shared"
            shared_dir.mkdir(parents=True, exist_ok=True)
            # Sweep stale shares (>1 h) before writing a new one so the
            # directory doesn't grow unboundedly with orphaned files.
            _prune_old_shared_photos()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            token = _sec.token_hex(6)
            out_path = shared_dir / f"share-{ts}-{token}.jpg"
            # Best-effort EXIF-correct save; fall back to raw bytes.
            try:
                from house_demo.states import _save_oriented_jpeg
                await asyncio.to_thread(_save_oriented_jpeg, data, out_path)
            except Exception:
                out_path.write_bytes(data)

            resp = RedirectResponse(url="/inventory/capture", status_code=303)
            # Short-lived (5 min), HttpOnly, same-site cookie. Plain value —
            # the path is local-only and the user is already authenticated.
            resp.set_cookie(
                "gyst_shared_photo",
                str(out_path),
                max_age=300,
                httponly=True,
                samesite="lax",
                path="/",
            )
            return resp

    # No image — disambiguate text/url via a small picker page.
    combined_text = "\n".join(p for p in (title, text, url_field) if p)
    params = urlencode({"text": combined_text}, quote_via=quote)
    return RedirectResponse(url=f"/share-handoff?{params}", status_code=303)


async def push_test(request: Request):
    """Send a one-off test push to every subscription the current user has."""
    from starlette.responses import JSONResponse
    _check_csrf_origin(request)
    user = _require_request_auth(request)
    result = push_db.send_to_user(
        int(user["id"]),
        title="GYST",
        body=f"Hi {user.get('name', 'there')} — push notifications are working.",
        url="/",
    )
    return JSONResponse(result)


_underlying = getattr(app, "_api", None) or getattr(app, "api", None)
if _underlying is not None:
    _underlying.add_route("/photo/{filename}", serve_photo, methods=["GET"])
    _underlying.add_route(
        "/photo_crop/{item_id}", serve_item_crop, methods=["GET"]
    )
    _underlying.add_route(
        "/chore_photo/{filename}", serve_chore_photo, methods=["GET"]
    )
    _underlying.add_route(
        "/push/vapid-public-key", push_vapid_public_key, methods=["GET"]
    )
    _underlying.add_route(
        "/push/subscribe", push_subscribe, methods=["POST"]
    )
    _underlying.add_route(
        "/push/unsubscribe", push_unsubscribe, methods=["POST"]
    )
    _underlying.add_route(
        "/push/test", push_test, methods=["POST"]
    )
    _underlying.add_route(
        "/calendar.ics", serve_ical, methods=["GET"]
    )
    _underlying.add_route(
        "/api/scan-product", api_scan_product, methods=["POST"]
    )
    _underlying.add_route(
        "/api/capture-upload", api_capture_upload, methods=["POST"]
    )
    # PWA Web Share Target — receives "Share to GYST" from any app.
    _underlying.add_route(
        "/share-target", share_target, methods=["POST", "GET"]
    )
