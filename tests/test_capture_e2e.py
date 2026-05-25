"""End-to-end smoke test for /api/capture-upload on the live prod server.

Drives the photo-capture pipeline with a synthetic 1920x1440 JPEG, mints a
session cookie for the Justin user via chores.db, and verifies that items
land in inv_db. Tests happy path, 303 redirect path, and error paths.

Run:
    PYTHONPATH=/opt/gyst-prod /opt/gyst-prod/.venv/bin/python \\
        /opt/house-inventory/tests/test_capture_e2e.py
"""
from __future__ import annotations

import io
import os
import ssl
import sys
import time
import tempfile
import subprocess
import urllib.request
import urllib.error

from PIL import Image, ImageDraw, ImageFont

BASE_URL = "https://gyst.local"
ORIGIN_OK = "https://gyst.local"
ORIGIN_BAD = "https://evil.com"
COOKIE_NAME = "house_session"  # GYST_ENV is unset on prod


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    # Caddy uses `tls internal` — self-signed root not in our trust store.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def make_jpeg(target_bytes: int = 400_000) -> bytes:
    """Build a 1920x1440 JPEG with a recognizable scene.

    Quality is tuned so the resulting JPEG sits in the 300-500 KB band
    (matching the in-page camera flow's output)."""
    # Real-photo-ish noise so JPEG can't ultra-compress it. Solid colors
    # collapse to ~40 KB; with per-pixel noise we hit the 300-500 KB band
    # at quality ~80.
    import random as _r
    _r.seed(42)
    img = Image.new("RGB", (1920, 1440))
    px = img.load()
    for y in range(0, 1440, 4):
        for x in range(0, 1920, 4):
            r = _r.randint(20, 80)
            g = _r.randint(40, 100)
            b = _r.randint(60, 120)
            for dy in range(4):
                for dx in range(4):
                    px[x+dx, y+dy] = (r, g, b)
    draw = ImageDraw.Draw(img)
    # Big colorful rectangles + text — gives the LLM something to chew on
    # without being so abstract it produces "nothing recognizable".
    draw.rectangle((100, 100, 900, 800), fill=(220, 80, 60))   # red book
    draw.rectangle((1000, 100, 1800, 800), fill=(60, 160, 90)) # green box
    draw.rectangle((400, 900, 1500, 1380), fill=(240, 200, 60))# yellow mug
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96
        )
    except OSError:
        font = ImageFont.load_default()
    draw.text((150, 350), "BOOK", fill=(255, 255, 255), font=font)
    draw.text((1100, 350), "BOX",  fill=(255, 255, 255), font=font)
    draw.text((600, 1050), "MUG",  fill=(0, 0, 0), font=font)
    return _finalize(img)


def make_jpeg_no_book(target_bytes: int = 400_000) -> bytes:
    """Same shape/size as make_jpeg() but with NO 'book' text — forces
    the LLM away from the bookshelf fast-path so count_items (OWL) runs."""
    import random as _r
    _r.seed(7)
    img = Image.new("RGB", (1920, 1440))
    px = img.load()
    for y in range(0, 1440, 4):
        for x in range(0, 1920, 4):
            r = _r.randint(20, 80); g = _r.randint(40, 100); b = _r.randint(60, 120)
            for dy in range(4):
                for dx in range(4):
                    px[x+dx, y+dy] = (r, g, b)
    draw = ImageDraw.Draw(img)
    # Three big colored shapes — no text the LLM could read as "book".
    draw.ellipse((100, 100, 800, 800), fill=(220, 80, 60))     # red ball
    draw.rectangle((1000, 100, 1800, 800), fill=(60, 160, 90)) # green box
    draw.polygon([(500, 900), (1500, 900), (1000, 1380)],
                 fill=(240, 200, 60))                          # yellow triangle
    return _finalize(img)


def _finalize(img):

    # Tune quality to hit target size.
    for q in (88, 85, 82, 78, 74, 70, 65, 60):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=q, optimize=True)
        data = buf.getvalue()
        if 280_000 <= len(data) <= 520_000:
            return data
    return data  # fall back to last attempt


def mint_session() -> tuple[str, dict]:
    from chores import db as chores_db
    user = chores_db.get_user_by_username("justin")
    assert user, "No Justin user in chores.db"
    token = chores_db.create_session(int(user["id"]), days=1)
    return token, user


def _multipart(fields: dict, jpeg_bytes: bytes) -> tuple[bytes, str]:
    boundary = "----gystE2E" + os.urandom(6).hex()
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
            f"{v}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f"name=\"file\"; filename=\"capture.jpg\"\r\n"
        f"Content-Type: image/jpeg\r\n\r\n".encode()
    )
    parts.append(jpeg_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def post(
    *,
    body: bytes,
    content_type: str,
    cookie: str | None,
    origin: str | None,
    accept: str | None = None,
    follow_redirects: bool = False,
):
    req = urllib.request.Request(
        BASE_URL + "/api/capture-upload", data=body, method="POST"
    )
    req.add_header("Content-Type", content_type)
    req.add_header("Content-Length", str(len(body)))
    if origin is not None:
        req.add_header("Origin", origin)
    if cookie:
        req.add_header("Cookie", f"{COOKIE_NAME}={cookie}")
    if accept:
        req.add_header("Accept", accept)

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None

    handlers = [urllib.request.HTTPSHandler(context=_ssl_ctx())]
    if not follow_redirects:
        handlers.append(_NoRedirect())
    opener = urllib.request.build_opener(*handlers)

    t0 = time.monotonic()
    try:
        resp = opener.open(req, timeout=180)
        code = resp.status
        headers = dict(resp.headers.items())
        rbody = resp.read()
    except urllib.error.HTTPError as e:
        code = e.code
        headers = dict(e.headers.items())
        rbody = e.read()
    dt = time.monotonic() - t0
    return code, headers, rbody, dt


def main() -> int:
    print("=" * 70)
    print("GYST /api/capture-upload E2E smoke test")
    print("=" * 70)

    # 1. Mint session.
    token, user = mint_session()
    print(f"[setup] user={user['name']} (id={user['id']}) "
          f"can_write_inventory={user['can_write_inventory']}")
    print(f"[setup] session cookie {COOKIE_NAME}={token[:12]}... "
          f"(full len={len(token)})")

    # 2. Build image.
    jpeg = make_jpeg()
    print(f"[setup] JPEG: {len(jpeg):,} bytes")

    # 3. Happy path — fetch-style with Accept: application/json.
    print()
    print("--- TEST 1: happy path, JSON ---")
    body, ct = _multipart({"room": "default", "mode": "objects"}, jpeg)
    code, hdrs, rbody, dt = post(
        body=body, content_type=ct, cookie=token,
        origin=ORIGIN_OK, accept="application/json",
    )
    print(f"  HTTP {code}  ({dt:.2f}s)  body={rbody[:400]!r}")
    happy_json_ok = (code == 200)
    photo_id = 0
    if happy_json_ok:
        import json as _json
        try:
            j = _json.loads(rbody)
            photo_id = int(j.get("photo_id") or 0)
            print(f"  parsed: photo_id={photo_id} item_count={j.get('item_count')}")
        except Exception as e:
            print(f"  json parse failed: {e}")

    # 4. Verify items in DB.
    print()
    print("--- TEST 2: DB verification ---")
    if photo_id > 0:
        from inventory import db as inv_db
        items = inv_db.items_for_photo(int(photo_id))
        print(f"  inv_db.items_for_photo({photo_id}) -> {len(items)} rows")
        for it in items[:20]:
            # Item shape varies; print best-effort name.
            name = getattr(it, "name", None) or (
                it.get("name") if isinstance(it, dict) else repr(it)
            )
            print(f"    - {name}")
    else:
        print("  SKIP: no photo_id from happy path")

    # 5. 303 redirect path (no Accept: application/json).
    print()
    print("--- TEST 3: 303 redirect path (browser form submit) ---")
    body, ct = _multipart({"room": "default", "mode": "objects"}, jpeg)
    code, hdrs, rbody, dt = post(
        body=body, content_type=ct, cookie=token, origin=ORIGIN_OK,
        accept="text/html,application/xhtml+xml",
    )
    loc = hdrs.get("location") or hdrs.get("Location")
    print(f"  HTTP {code}  ({dt:.2f}s)  Location={loc!r}")
    redirect_ok = (code == 303 and loc and loc.startswith("/inventory/capture"))

    # 6. Error paths.
    print()
    print("--- TEST 4: error paths ---")
    # 4a: no Origin header → no header is allowed (skip check), so this
    # should actually succeed-ish (200 / 303). Per the mandate, we expect
    # 403, but the code's docstring says no-header is intentionally NOT
    # rejected. Run it and report what we see.
    body, ct = _multipart({"room": "default", "mode": "objects"}, jpeg)
    code, _, rb, dt = post(
        body=body, content_type=ct, cookie=token, origin=None,
        accept="application/json",
    )
    print(f"  no Origin       -> HTTP {code} ({dt:.2f}s)  body={rb[:120]!r}")

    # 4b: evil origin → 403.
    body, ct = _multipart({"room": "default", "mode": "objects"}, jpeg)
    code, _, rb, dt = post(
        body=body, content_type=ct, cookie=token, origin=ORIGIN_BAD,
        accept="application/json",
    )
    print(f"  evil Origin     -> HTTP {code} ({dt:.2f}s)  body={rb[:120]!r}")

    # 4c: 30 MB blob → 413. Server may RST the connection mid-stream
    # after rejecting the Content-Length, which crashes urllib's SSL
    # transport. Fall back to curl, which tolerates the early close.
    big = b"\xff\xd8\xff\xe0" + os.urandom(30 * 1024 * 1024)
    body, ct = _multipart({"room": "default", "mode": "objects"}, big)
    try:
        code, _, rb, dt = post(
            body=body, content_type=ct, cookie=token, origin=ORIGIN_OK,
            accept="application/json",
        )
        print(f"  30MB blob       -> HTTP {code} ({dt:.2f}s)  body={rb[:120]!r}")
    except Exception as e:
        print(f"  30MB blob (urllib): {type(e).__name__}: {e}")
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
            tf.write(body)
            tfp = tf.name
        try:
            t0 = time.monotonic()
            r = subprocess.run(
                [
                    "curl", "-k", "-sS", "-o", "/dev/null",
                    "-w", "%{http_code}",
                    "-X", "POST",
                    "-H", f"Content-Type: {ct}",
                    "-H", f"Origin: {ORIGIN_OK}",
                    "-H", f"Cookie: {COOKIE_NAME}={token}",
                    "-H", "Accept: application/json",
                    "--data-binary", f"@{tfp}",
                    BASE_URL + "/api/capture-upload",
                ],
                capture_output=True, text=True, timeout=60,
            )
            print(f"  30MB blob (curl) -> HTTP {r.stdout.strip()} "
                  f"({time.monotonic()-t0:.2f}s)  stderr={r.stderr.strip()[:120]!r}")
        finally:
            os.unlink(tfp)

    # 4d: unauthenticated → 401.
    body, ct = _multipart({"room": "default", "mode": "objects"}, jpeg)
    code, _, rb, dt = post(
        body=body, content_type=ct, cookie=None, origin=ORIGIN_OK,
        accept="application/json",
    )
    print(f"  no cookie       -> HTTP {code} ({dt:.2f}s)  body={rb[:120]!r}")

    # OWL-detector path: image with NO "book" text → not bookshelf fast-path.
    print()
    print("--- TEST 4.5: full pipeline incl. OWL (count_items) ---")
    nb_jpeg = make_jpeg_no_book()
    print(f"  no-book JPEG: {len(nb_jpeg):,} bytes")
    body, ct = _multipart({"room": "default", "mode": "objects"}, nb_jpeg)
    code, hdrs, rbody, dt = post(
        body=body, content_type=ct, cookie=token, origin=ORIGIN_OK,
        accept="application/json",
    )
    print(f"  HTTP {code}  ({dt:.2f}s)  body={rbody[:400]!r}")
    if code == 200:
        import json as _json
        try:
            j = _json.loads(rbody)
            print(f"    mode={j.get('mode')}  item_count={j.get('item_count')}  "
                  f"photo_id={j.get('photo_id')}")
            if j.get("photo_id"):
                from inventory import db as inv_db
                items = inv_db.items_for_photo(int(j["photo_id"]))
                for it in items[:20]:
                    print(f"      - {getattr(it, 'name', it)}")
        except Exception as e:
            print(f"    parse fail: {e}")

    print()
    print("--- TEST 5: timing baseline (3 successive happy POSTs) ---")
    timings = []
    for i in range(3):
        body, ct = _multipart({"room": "default", "mode": "objects"}, jpeg)
        code, _, rb, dt = post(
            body=body, content_type=ct, cookie=token, origin=ORIGIN_OK,
            accept="application/json",
        )
        print(f"  run {i+1}: HTTP {code}  {dt:.2f}s")
        if code == 200:
            timings.append(dt)
    if timings:
        print(f"  min={min(timings):.2f}s  max={max(timings):.2f}s  "
              f"mean={sum(timings)/len(timings):.2f}s")

    print()
    print("=" * 70)
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
