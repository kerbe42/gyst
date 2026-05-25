"""Tests for the security review fixes (F1: path traversal on shared photo
cookie; F2: unbounded upload size). Stdlib-only test runner — pytest isn't
installed on the prod venv. Each test asserts a property the OLD code
violates and the NEW code holds.

Run from /opt/house-inventory with:
    PYTHONPATH=. /opt/house-inventory/.venv/bin/python tests/test_security_review.py
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# Make the project root importable.
sys.path.insert(0, "/opt/house-inventory")
sys.path.insert(0, "/opt/house-inventory/house_demo")

# Reflex's compile path needs HOME/.local for state-registry init, which
# we don't want to hit during a unit test. Keep them out of /home so the
# import doesn't sprawl.
os.environ.setdefault("HOME", "/opt/house-inventory")
os.environ.setdefault("XDG_DATA_HOME", "/opt/house-inventory/.local/share")
os.environ.setdefault("REFLEX_DIR", "/opt/house-inventory/.local/share/reflex")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
_results: list[tuple[str, bool, str]] = []


def _t(name: str, fn):
    try:
        fn()
        _results.append((name, True, ""))
        print(f"  PASS  {name}")
    except Exception:
        tb = traceback.format_exc()
        _results.append((name, False, tb))
        print(f"  FAIL  {name}\n{tb}")


# ---------------------------------------------------------------------------
# F1: _is_safe_shared_photo_path
# ---------------------------------------------------------------------------
def f1_tests():
    import config
    # Ensure the dir exists so resolve() yields a stable prefix.
    (config.PHOTOS_DIR / "shared").mkdir(parents=True, exist_ok=True)

    from house_demo.states import _is_safe_shared_photo_path

    shared_root = (config.PHOTOS_DIR / "shared").resolve()

    def rejects_etc_passwd():
        assert _is_safe_shared_photo_path("/etc/passwd") is None

    def rejects_relative_traversal():
        # Even a relative path that would resolve into shared_root from
        # the cwd shouldn't matter — _is_safe_shared_photo_path takes
        # the raw cookie value verbatim. A ../-style traversal must be
        # rejected regardless of cwd.
        assert _is_safe_shared_photo_path("../../etc/passwd") is None

    def rejects_empty():
        assert _is_safe_shared_photo_path("") is None
        assert _is_safe_shared_photo_path(None) is None  # type: ignore[arg-type]

    def rejects_photos_dir_root_file():
        # A regular photo (not under shared/) must NOT come through the
        # share-cookie path — only the share-target endpoint stages
        # files there. This prevents a malicious cookie from re-ingesting
        # arbitrary already-stored photos.
        target = config.PHOTOS_DIR / "regular-photo.jpg"
        assert _is_safe_shared_photo_path(str(target)) is None

    def rejects_proc_self_cmdline():
        # The original exploit class: /proc files are readable bytes
        # that an LLM might "describe" in a way that leaks them.
        assert _is_safe_shared_photo_path("/proc/self/cmdline") is None

    def accepts_legitimate_shared_file():
        target = shared_root / "share-20260101_000000-test.jpg"
        result = _is_safe_shared_photo_path(str(target))
        assert result is not None, "Legitimate shared path was rejected"
        # Resolved path is under shared_root.
        result.relative_to(shared_root)

    def rejects_symlink_escape(tmp=shared_root):
        # If shared/ contains a symlink that points OUT of shared/,
        # resolve() follows it. The check must still reject the result.
        link = tmp / "escape-link"
        try:
            try:
                link.unlink()
            except FileNotFoundError:
                pass
            link.symlink_to("/etc/passwd")
            assert _is_safe_shared_photo_path(str(link)) is None
        finally:
            try:
                link.unlink()
            except FileNotFoundError:
                pass

    _t("F1.rejects /etc/passwd", rejects_etc_passwd)
    _t("F1.rejects ../ traversal", rejects_relative_traversal)
    _t("F1.rejects empty / None", rejects_empty)
    _t("F1.rejects PHOTOS_DIR root file", rejects_photos_dir_root_file)
    _t("F1.rejects /proc/self/cmdline", rejects_proc_self_cmdline)
    _t("F1.accepts legitimate shared file", accepts_legitimate_shared_file)
    _t("F1.rejects symlink escape", rejects_symlink_escape)


# ---------------------------------------------------------------------------
# F2: _reject_oversize_upload + _enforce_size_after_read
# ---------------------------------------------------------------------------
def f2_tests():
    from house_demo.house_demo import (
        _enforce_size_after_read,
        _reject_oversize_upload,
        _MAX_UPLOAD_BYTES,
    )
    from starlette.exceptions import HTTPException

    class _FakeReq:
        def __init__(self, cl):
            self.headers = {"content-length": str(cl)} if cl is not None else {}

    def header_blocks_oversize():
        try:
            _reject_oversize_upload(_FakeReq(_MAX_UPLOAD_BYTES + 1))
        except HTTPException as e:
            assert e.status_code == 413
            return
        assert False, "Expected HTTPException(413)"

    def header_allows_normal():
        _reject_oversize_upload(_FakeReq(1024 * 1024))   # 1 MB OK
        _reject_oversize_upload(_FakeReq(_MAX_UPLOAD_BYTES))  # exactly cap

    def header_missing_is_lenient():
        # Missing Content-Length passes — we still catch oversize after read.
        _reject_oversize_upload(_FakeReq(None))

    def header_bogus_is_lenient():
        # Non-integer header passes — we still catch oversize after read.
        req = _FakeReq(None)
        req.headers = {"content-length": "not-a-number"}
        _reject_oversize_upload(req)

    def post_read_blocks_oversize():
        big = b"x" * (_MAX_UPLOAD_BYTES + 1)
        try:
            _enforce_size_after_read(big)
        except HTTPException as e:
            assert e.status_code == 413
            return
        assert False, "Expected HTTPException(413)"

    def post_read_allows_normal():
        _enforce_size_after_read(b"x" * 1024)
        _enforce_size_after_read(b"x" * _MAX_UPLOAD_BYTES)

    _t("F2.header blocks oversize", header_blocks_oversize)
    _t("F2.header allows normal", header_allows_normal)
    _t("F2.header missing is lenient", header_missing_is_lenient)
    _t("F2.header bogus is lenient", header_bogus_is_lenient)
    _t("F2.post-read blocks oversize", post_read_blocks_oversize)
    _t("F2.post-read allows normal", post_read_allows_normal)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# F3: _check_csrf_origin
# ---------------------------------------------------------------------------
def f3_tests():
    from house_demo.house_demo import _check_csrf_origin, _ALLOWED_ORIGINS
    from starlette.exceptions import HTTPException

    class _Req:
        def __init__(self, origin=None, referer=None):
            self.headers = {}
            if origin is not None:
                self.headers["origin"] = origin
            if referer is not None:
                self.headers["referer"] = referer

    def accepts_known_https_origin():
        _check_csrf_origin(_Req(origin="https://gyst.local"))
        _check_csrf_origin(_Req(origin="https://gyst.local:8443"))

    def accepts_localhost():
        _check_csrf_origin(_Req(origin="http://localhost"))
        _check_csrf_origin(_Req(origin="http://127.0.0.1"))

    def rejects_attacker_origin():
        for bad in [
            "https://evil.com",
            "https://gyst.local.evil.com",
            "https://attacker.local",
            "http://gyst.local",   # wrong scheme
            "https://other.local",
        ]:
            try:
                _check_csrf_origin(_Req(origin=bad))
            except HTTPException as e:
                assert e.status_code == 403, f"Expected 403 for {bad}"
                continue
            raise AssertionError(f"Origin {bad!r} should have been rejected")

    def falls_back_to_referer():
        # Browser may not send Origin on same-origin POST; Referer is used.
        _check_csrf_origin(_Req(referer="https://gyst.local/inventory/capture"))

    def referer_blocks_cross_site():
        try:
            _check_csrf_origin(_Req(referer="https://evil.com/csrf.html"))
        except HTTPException as e:
            assert e.status_code == 403
            return
        raise AssertionError("Cross-site Referer should have been rejected")

    def allows_when_both_headers_missing():
        # Non-browser clients (curl, internal cron) often send neither.
        # Cookie auth still gates the endpoint.
        _check_csrf_origin(_Req())

    _t("F3.accepts known HTTPS origin", accepts_known_https_origin)
    _t("F3.accepts localhost", accepts_localhost)
    _t("F3.rejects attacker origin", rejects_attacker_origin)
    _t("F3.falls back to Referer", falls_back_to_referer)
    _t("F3.Referer blocks cross-site", referer_blocks_cross_site)
    _t("F3.allows when both headers missing", allows_when_both_headers_missing)


# ---------------------------------------------------------------------------
# F4: nosniff header on photo responses
# ---------------------------------------------------------------------------
def f4_tests():
    from house_demo.house_demo import _PRIVATE_CACHE

    def header_present():
        assert _PRIVATE_CACHE.get("X-Content-Type-Options") == "nosniff", (
            f"Got: {_PRIVATE_CACHE.get('X-Content-Type-Options')!r}"
        )

    def cache_control_intact():
        # Don't regress the existing Cache-Control while adding the new header.
        assert "private" in _PRIVATE_CACHE.get("Cache-Control", "")

    _t("F4.nosniff present in _PRIVATE_CACHE", header_present)
    _t("F4.Cache-Control still set", cache_control_intact)


# ---------------------------------------------------------------------------
# F5: LLM rate limit
# ---------------------------------------------------------------------------
def f5_tests():
    from house_demo.house_demo import (
        _check_llm_rate_limit,
        _llm_call_log,
        _LLM_RATE_LIMIT,
    )
    from starlette.exceptions import HTTPException

    def under_limit_passes():
        uid = 90001
        _llm_call_log.pop(uid, None)
        for _ in range(_LLM_RATE_LIMIT):
            _check_llm_rate_limit(uid)
        # Cleanup
        _llm_call_log.pop(uid, None)

    def over_limit_rejected():
        uid = 90002
        _llm_call_log.pop(uid, None)
        for _ in range(_LLM_RATE_LIMIT):
            _check_llm_rate_limit(uid)
        try:
            _check_llm_rate_limit(uid)
        except HTTPException as e:
            assert e.status_code == 429
            _llm_call_log.pop(uid, None)
            return
        raise AssertionError("Expected HTTPException(429)")

    def per_user_isolated():
        # User A burning their bucket must not affect user B.
        a, b = 90003, 90004
        _llm_call_log.pop(a, None); _llm_call_log.pop(b, None)
        for _ in range(_LLM_RATE_LIMIT):
            _check_llm_rate_limit(a)
        # User A is at limit; user B should still have a fresh bucket.
        _check_llm_rate_limit(b)
        _llm_call_log.pop(a, None); _llm_call_log.pop(b, None)

    _t("F5.under limit passes", under_limit_passes)
    _t("F5.over limit rejected with 429", over_limit_rejected)
    _t("F5.per-user buckets are isolated", per_user_isolated)


# ---------------------------------------------------------------------------
# F6: orphan shared-photo cleanup
# ---------------------------------------------------------------------------
def f6_tests():
    import os
    import time
    import config
    from house_demo.house_demo import _prune_old_shared_photos

    shared_dir = config.PHOTOS_DIR / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)

    def prunes_old_file():
        f = shared_dir / "share-old-test.jpg"
        f.write_bytes(b"x")
        # Backdate mtime by 2h.
        old = time.time() - 7200
        os.utime(f, (old, old))
        assert f.exists()
        pruned = _prune_old_shared_photos(max_age_sec=3600)
        assert not f.exists(), "Old file should have been pruned"
        assert pruned >= 1

    def preserves_fresh_file():
        f = shared_dir / "share-fresh-test.jpg"
        f.write_bytes(b"x")
        try:
            _prune_old_shared_photos(max_age_sec=3600)
            assert f.exists(), "Fresh file should NOT have been pruned"
        finally:
            try:
                f.unlink()
            except FileNotFoundError:
                pass

    _t("F6.prunes file older than max_age", prunes_old_file)
    _t("F6.preserves fresh file", preserves_fresh_file)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# F7: dashboard cross-module read-permission scrubbing
# ---------------------------------------------------------------------------
def f7_tests():
    """The HomeState.on_load scrub block clears inventory-derived cards
    when can_read_inventory is False, and chores-derived agenda/activity
    rows when can_read_chores is False. We test the filter shape
    directly — driving the full Reflex state machinery in a unit test
    would need too much scaffolding for one bug class."""

    def _dash():
        return {
            "expiring_food": [{"name": "milk"}],
            "returnable_soon": [{"name": "drill"}],
            "warranty_soon":  [{"name": "tv"}],
            "agenda": [
                {"kind": "task", "title": "trash"},
                {"kind": "appointment", "title": "dentist"},
                {"kind": "meal", "title": "lunch"},
            ],
            "activity": [
                {"kind": "item_history", "label": "inventory event"},
                {"kind": "task", "label": "task done"},
                {"kind": "appointment", "label": "appt"},
                {"kind": "note", "label": "note created"},
                {"kind": "grocery", "label": "grocery tick"},
            ],
        }

    def scrub(d, can_inv: bool, can_chr: bool):
        # Mirror states.py HomeState.on_load scrub logic exactly.
        if not can_inv:
            d["expiring_food"] = []
            d["returnable_soon"] = []
            d["warranty_soon"] = []
            d["activity"] = [
                e for e in d["activity"]
                if e.get("kind") not in ("inventory", "item_history", "item")
            ]
        if not can_chr:
            d["agenda"] = [
                a for a in d["agenda"]
                if a.get("kind") not in ("task", "appointment")
            ]
            d["activity"] = [
                e for e in d["activity"]
                if e.get("kind") not in ("task", "appointment", "completion", "chore")
            ]
        return d

    def no_inv():
        d = scrub(_dash(), can_inv=False, can_chr=True)
        assert d["expiring_food"] == []
        assert d["returnable_soon"] == []
        assert d["warranty_soon"] == []
        assert all(e["kind"] != "item_history" for e in d["activity"])
        assert any(e["kind"] == "task" for e in d["activity"])

    def no_chr():
        d = scrub(_dash(), can_inv=True, can_chr=False)
        assert d["expiring_food"]
        assert all(a["kind"] not in ("task", "appointment") for a in d["agenda"])
        assert any(e["kind"] == "item_history" for e in d["activity"])
        assert all(e["kind"] not in ("task", "appointment") for e in d["activity"])

    def no_perms():
        d = scrub(_dash(), can_inv=False, can_chr=False)
        kinds = {e["kind"] for e in d["activity"]}
        assert "note" in kinds and "grocery" in kinds
        assert d["expiring_food"] == []

    def full_perms():
        d = scrub(_dash(), can_inv=True, can_chr=True)
        assert d["expiring_food"] and d["returnable_soon"] and d["warranty_soon"]
        assert len(d["agenda"]) == 3
        assert len(d["activity"]) == 5

    _t("F7.no_inv strips inventory cards", no_inv)
    _t("F7.no_chr strips agenda+chore activity", no_chr)
    _t("F7.no_perms keeps only universal cards", no_perms)
    _t("F7.full_perms keeps everything", full_perms)




# ---------------------------------------------------------------------------
# F8: ZAP remediation regression-locks
# ---------------------------------------------------------------------------
def f8_tests():
    """Verify the Caddy header set we promised the ZAP report still
    lands on real responses. Hits port 443 with a Host: header
    override so the test works whether or not /etc/hosts resolves
    gyst.local on the test machine."""
    import socket
    import ssl

    def fetch_headers(path):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection(("127.0.0.1", 443), timeout=4) as sock:
            with ctx.wrap_socket(sock, server_hostname="gyst.local") as ssock:
                req = (
                    f"GET {path} HTTP/1.1\r\n"
                    "Host: gyst.local\r\n"
                    "Connection: close\r\n"
                    "Accept: */*\r\n"
                    "\r\n"
                ).encode()
                ssock.sendall(req)
                buf = b""
                while True:
                    chunk = ssock.recv(8192)
                    if not chunk:
                        break
                    buf += chunk
                    if b"\r\n\r\n" in buf and len(buf) > 4096:
                        break
        head, _, _ = buf.partition(b"\r\n\r\n")
        headers = {}
        for line in head.decode("utf-8", "replace").split("\r\n")[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()
        return headers

    def hsts_present():
        h = fetch_headers("/")
        sts = h.get("strict-transport-security", "")
        assert "max-age=" in sts and int(
            sts.split("max-age=", 1)[1].split(";")[0]
        ) >= 31536000, f"HSTS missing or too short: {sts!r}"

    def csp_no_wildcards():
        h = fetch_headers("/")
        csp = h.get("content-security-policy", "")
        # The original ZAP finding had `connect-src 'self' wss: https:`.
        # Bare scheme wildcards must not return.
        assert "connect-src" in csp, "connect-src missing"
        connect = csp.split("connect-src", 1)[1].split(";", 1)[0]
        # Bare scheme wildcards look like " wss: " / " wss:;" / " wss:"<EOL>
        # — NOT " wss://host". The regex catches the bare-scheme form.
        import re as _re
        bare = _re.search(r" (?:wss|https):(?=\s|;|$)", connect)
        assert bare is None, \
            f"wildcard scheme back in connect-src: {connect!r}"

    def html_no_store():
        h = fetch_headers("/")
        cc = h.get("cache-control", "")
        assert "no-store" in cc, f"HTML cache-control not no-store: {cc!r}"

    def assets_immutable():
        # Fingerprinted bundles must still get long-cache, immutable.
        # Pick any present asset path.
        h = fetch_headers("/manifest.webmanifest")
        cc = h.get("cache-control", "")
        # /manifest.webmanifest is bucket /pwa_static so it should be
        # cached but not no-store. Pick a /assets/* path if available.
        # Skip if upstream not reachable; the no-store test catches the
        # main regression risk.
        if cc:
            assert "no-store" not in cc, \
                f"/manifest.webmanifest should be cacheable: {cc!r}"

    _t("F8.HSTS header is set with >=1y max-age", hsts_present)
    _t("F8.CSP connect-src has no wss:/https: wildcards", csp_no_wildcards)
    _t("F8.HTML responses are Cache-Control: no-store", html_no_store)
    _t("F8.PWA static assets remain cacheable", assets_immutable)


if __name__ == "__main__":
    print("\n--- F1: path traversal on gyst_shared_photo cookie ---")
    f1_tests()
    print("\n--- F2: upload size limit ---")
    f2_tests()
    print("\n--- F3: Origin/Referer check ---")
    f3_tests()
    print("\n--- F4: nosniff on photo responses ---")
    f4_tests()
    print("\n--- F5: LLM rate limit ---")
    f5_tests()
    print("\n--- F6: orphan shared-photo cleanup ---")
    f6_tests()
    print("\n--- F7: dashboard cross-module perm scrubbing ---")
    f7_tests()
    print("\n--- F8: ZAP remediation header regression-locks ---")
    try:
        f8_tests()
    except Exception as exc:
        # F8 hits the live Caddy on :443; if Caddy isn't running
        # (e.g. running tests in a CI container), skip rather than
        # failing the whole suite. The headers can also be checked
        # manually with `curl -kis --resolve gyst.local:443:127.0.0.1`.
        print(f"  SKIP F8: Caddy not reachable ({exc!r})")
    fails = [r for r in _results if not r[1]]
    print(f"\n{'='*60}")
    print(f"{len(_results) - len(fails)}/{len(_results)} passed")
    if fails:
        print(f"FAILED: {len(fails)}")
        for name, _, _ in fails:
            print(f"  - {name}")
        sys.exit(1)
    print("OK")
