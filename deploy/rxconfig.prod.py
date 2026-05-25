"""Reflex configuration — PROD.

This file is copied to /opt/gyst-prod/house_demo/rxconfig.py by
deploy/clone-to-prod.sh and deploy/sync-to-prod.sh. Do NOT edit the
copy on prod directly; edit this template under /opt/house-inventory/deploy/
and re-run sync-to-prod.sh.

- Reflex binds to 127.0.0.1:3002 (frontend + backend on the same port).
- Caddy on the host terminates TLS on :443 and reverse-proxies to :3002.
- `api_url` is the public origin Caddy serves on, so the browser's
  WebSocket dials back to https://<host>/_event instead of the internal
  port.
"""

import os

import reflex as rx

# Override at deploy time if the public hostname changes:
#   sudo systemctl set-environment GYST_PUBLIC_ORIGIN=https://gyst.example.com
PUBLIC_ORIGIN = os.environ.get("GYST_PUBLIC_ORIGIN", "https://localhost")

config = rx.Config(
    app_name="house_demo",
    frontend_port=3002,
    backend_port=3002,
    # Bind only to loopback — Caddy is the only thing that should talk to us.
    backend_host="127.0.0.1",
    api_url=PUBLIC_ORIGIN,
    deploy_url=PUBLIC_ORIGIN,
    show_built_with_reflex=False,
    env=rx.Env.PROD,
    plugins=[
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(
                appearance="dark",
                has_background=True,
                radius="large",
                accent_color="indigo",
                gray_color="slate",
                panel_background="solid",
            ),
        ),
    ],
)
