# GYST — Get Your Stuff Together

Self-hosted household management platform. Inventory, chores, groceries, meal planning, notes, appointments, and a Claude/OpenAI-powered assistant that can read and write all of it. Runs on a single host (or a single Docker container), serves a PWA your phone can install.

Take a photo of a shelf — the LLM identifies what's on it and files each item under the right room. Tap an item later to mark it for sale, move it to another room, or send it to the trash. Hold the omnibox mic, say *"add take out the trash to my tasks tomorrow"*, and JARVIS does it. Scan a barcode and the item auto-populates with name, image, and an estimated value in your local currency.

## What's in the box

| | |
|---|---|
| **Inventory** | Add via camera, gallery upload, or barcode scan. Browse by room, search by name/category, edit, soft-delete + undo. Per-photo grouping with thumbnails. |
| **Chores & tasks** | Recurring or one-off, assigned to people, due-date aware, optional proof-photo on completion. |
| **Food (unified)** | Pantry, shopping list, meal plan in one nav section. Pick a recipe and missing ingredients flow automatically to the shopping list. |
| **Notes** | Quick-add by Enter, longer notes with body + mic dictation + "Polish with AI." Pin to top. |
| **Appointments** | Calendar with home-page surfacing of next-24-hour events. |
| **JARVIS assistant** | Anthropic Claude or OpenAI, 40+ tools spanning every entity. Voice in (Web Speech API), voice out (Web Speech Synthesis) with conversation-loop auto-restart. |
| **PWA** | Manifest, service worker, VAPID push, share-target intent (share a photo from another app → GYST captures it). |
| **Admin settings** | Users, roles, rooms, announcements, audit log, currency + time zone, LLM provider + API keys. |

## Quickstart — Docker

The fastest way to run GYST end-to-end is the bundled Dockerfile:

```bash
cd docker
# REQUIRED if you'll visit the page from anything other than the
# docker host itself. Bake the public URL into the JS bundle:
export GYST_PUBLIC_ORIGIN="https://your-host.example.com:10443"
docker compose up -d --build
# wait ~90s for Reflex to compile, then:
open "$GYST_PUBLIC_ORIGIN/"
```

The container ships its own Caddy (TLS, security headers, cache-control) and a single Reflex/Granian backend. SQLite DBs and photos live in the `gyst-docker-data` named volume.

> **Important**: `GYST_PUBLIC_ORIGIN` is compiled into the frontend bundle. If you don't set it to the exact URL users will visit, the page loads but the splash screen stays forever (the WebSocket can't connect). Default is `https://localhost:10443` which only works on the docker host itself. To change it later, edit `docker-compose.yml` or the env, then `docker compose down && docker compose up -d` (recreate forces a recompile).
>
> The first visit shows a TLS warning because the container mints certs from its own internal CA. Accept once and the browser remembers.
>
> If you're running on a host that already runs Caddy with `tls internal`, the compose file optionally bind-mounts the host's CA so certs chain to a trusted root. See `docker/docker-compose.yml`.

Useful lifecycle commands:

```bash
docker compose logs -f          # live tail
docker compose restart          # no rebuild
docker compose down             # stop (keeps data volume)
docker compose down -v          # ALSO drop the data volume (fresh DBs)
```

## Quickstart — local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd house_demo
reflex run --env prod --loglevel info
# backend on http://127.0.0.1:3000 (Reflex default)
```

For full functionality you'll also want:

- An LLM API key (Anthropic recommended; OpenAI also supported). Set via Settings → API once the app is up, or seed `app_settings/db.py` directly.
- A reverse proxy with TLS in front (Caddy, nginx, traefik). PWA features, camera, microphone, and the service worker all require HTTPS.
- VAPID keys for web push (optional). Generate via `python -m notifications.vapid_setup` and paste into Settings → API.

## Architecture

```
Browser ──HTTPS──▶ Caddy ──HTTP──▶ Reflex/Granian ──▶ SQLite DBs
                                        │
                                        ├──▶ Anthropic / OpenAI (assistant)
                                        ├──▶ Open Food Facts / UPCitemdb / Open Library (barcode)
                                        └──▶ Frankfurter (FX rates)
```

**Reflex 0.9** for the frontend (Python → React + WebSockets), served by **Granian** (Rust ASGI). **Caddy** terminates TLS, sets security headers, and routes cache buckets. Eleven SQLite databases, one per concern (`inventory`, `notes`, `chores`, `groceries`, `meals`, `appointments`, `announcements`, `auth`, `app_settings`, `audit`, `push`). All state local to the host — no cloud unless you point the LLM at one.

## Security

The repo ships a stdlib-only invariant suite at `tests/test_security_review.py` covering 34 properties across:

- **F1** — Path traversal on the shared-photo cookie
- **F2** — Upload size caps (pre-read + post-read)
- **F3** — Origin/Referer CSRF check on POSTs
- **F4** — `nosniff` on photo responses
- **F5** — LLM rate limit (per-user sliding window)
- **F6** — Orphan shared-photo cleanup
- **F7** — Cross-module permission scrubbing on the home dashboard
- **F8** — Caddy header regressions (HSTS, no-wildcard CSP, HTML `no-store`, /assets/* still cacheable)

Run with:

```bash
PYTHONPATH=. python tests/test_security_review.py
```

Authentication is PBKDF2-SHA256 at 600k iterations with cookie-backed sessions (30 days, HttpOnly + Secure + SameSite=Lax). Outbound image fetches go through an SSRF allow-list. Uploaded JPEGs are re-encoded via Pillow with `_save_oriented_jpeg` to strip EXIF and bound pixel size.

## Documentation

The full how-to + architecture/operator docs are rendered in-app at **/help** once the server is running (two tabs: end-user guide + application documentation).

Same content as Python source: see `house_demo/house_demo/pages.py` → `help_page()`.

## Repo layout

```
.
├── house_demo/                  # Reflex app (frontend + state)
│   ├── house_demo/
│   │   ├── house_demo.py        # entry + route registration
│   │   ├── layout.py            # sidebar, omnibox, layout()
│   │   ├── pages.py             # every page() function
│   │   ├── states.py            # every rx.State subclass
│   │   └── config.py            # categories, rooms, paths
│   └── assets/                  # static JS/CSS/icons/manifest/sw
├── inventory/ notes/ chores/    # one module per concern, each has db.py
├── groceries/ meals/ appointments/
├── announcements/ auth/ app_settings/ notifications/
├── assistant/                   # JARVIS: chat.py + tools.py + memory
├── tests/test_security_review.py
├── deploy/                      # sync-to-prod.sh + systemd units
├── docker/                      # Dockerfile, compose, container Caddyfile
└── scripts/                     # one-off maintenance scripts
```

## Stack at a glance

- Python 3.12, Reflex 0.9.2, Granian, Caddy
- SQLite (one DB per module, no ORM, plain sqlite3)
- Anthropic + OpenAI SDKs (`claude-haiku-4-5` default)
- Open Food Facts, UPCitemdb, Open Library, ZXing (browser fallback), native BarcodeDetector when available
- Frankfurter FX API (24h cached)
- Web Speech API (in + out), Web Push (VAPID), service worker, share-target

## License

**PolyForm Noncommercial 1.0.0** — see [LICENSE](LICENSE).

You can run it for your own household, study it, modify it, fork it, share it with friends, use it in a charity / school / research project. You **cannot** sell it, charge for hosting it, embed it in a commercial product, or use it to make money. No warranty.

If you want a commercial license, open an issue.

---

*Built for one household, but designed to be cloned and reshaped for yours.*
