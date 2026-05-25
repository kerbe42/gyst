"""Reflex configuration — DEV.

Lives at /opt/house-inventory/house_demo/rxconfig.py.

- Reflex binds to 127.0.0.1:3003 (frontend + backend on the same port).
- Caddy on the host serves https://gyst.local:8443 with `tls internal`
  and reverse-proxies to :3003.
- `api_url` is the public origin Caddy serves on, so the browser's
  WebSocket dials back to https://gyst.local:8443/_event.
"""

import os

import reflex as rx

PUBLIC_ORIGIN = os.environ.get("GYST_PUBLIC_ORIGIN", "https://gyst.local:8443")

config = rx.Config(
    app_name="house_demo",
    frontend_port=3003,
    backend_port=3003,
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
