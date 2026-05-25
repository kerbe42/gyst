# Dev → Prod deployment

Two parallel installs of the same app:

| Env  | Path                     | Internal port | Public URL                    | systemd unit         |
|------|--------------------------|---------------|-------------------------------|----------------------|
| dev  | `/opt/house-inventory`   | 3001          | `http://<host>:3001`          | `house-reflex`       |
| prod | `/opt/gyst-prod`         | 3002          | `https://<host>` (Caddy → 3002)| `gyst-prod`          |

Each install owns its own `data/` directory, so dev experiments never touch prod records.

## One-time setup

On the server, as root or via sudo:

```bash
cd /opt/house-inventory/deploy
sudo chmod +x clone-to-prod.sh sync-to-prod.sh
sudo bash clone-to-prod.sh

# Edit Caddyfile first — replace gyst.example.com with your hostname,
# or switch to the `tls internal` block for a self-signed cert.
sudoedit Caddyfile

sudo cp gyst-prod.service /etc/systemd/system/
sudo cp Caddyfile /etc/caddy/Caddyfile        # or merge with existing

# Tell prod what its public origin is (lets the session cookie set the
# Secure flag and points Reflex at the right WebSocket URL).
sudo systemctl edit gyst-prod    # add:
#   [Service]
#   Environment="GYST_PUBLIC_ORIGIN=https://your.host"

sudo systemctl daemon-reload
sudo systemctl enable --now gyst-prod
sudo systemctl reload caddy
```

After this, prod runs at `https://<host>` (Caddy issues a TLS cert automatically
via Let's Encrypt; for an internal-only deploy, switch the Caddyfile to
`tls internal` for a self-signed cert).

## Daily workflow

1. Make changes in `/opt/house-inventory` (the dev tree).
2. Restart dev to verify: `sudo systemctl restart house-reflex && sudo journalctl -u house-reflex -f`.
3. Drive through the change in your browser at `http://<host>:3001`.
4. When the change is solid, push it to prod:

   ```bash
   sudo /opt/house-inventory/deploy/sync-to-prod.sh
   ```

   This rsyncs **code only** (excluding `data/`, `.venv/`, `.web/`, databases,
   the master encryption key, and TLS material) from dev to prod, then
   restarts the prod service.

## What is and isn't synced

`sync-to-prod.sh` copies Python source, assets, prompts, requirements,
deploy scripts. It NEVER touches:

- `data/` — databases, photos, TLS, master key
- `.venv/` — prod has its own virtualenv
- `.web/` — Reflex regenerates this on next start
- `__pycache__/`
- `.git/`

That means schema changes (new tables, new columns) propagate via your
`init_db()` migrations, which run on prod startup. Settings like API keys,
user accounts, and uploaded photos stay separate per environment — set
them once in each.

## Rolling back

If prod breaks after a push, the easiest rollback is to re-run an older
version of dev through `sync-to-prod.sh`. For surgical rollback, keep an
on-server snapshot:

```bash
sudo tar -czf /var/backups/gyst-prod-pre-$(date +%F-%H%M).tgz \
    --exclude='.venv' --exclude='.web' --exclude='data' /opt/gyst-prod
```

`sync-to-prod.sh` snapshots automatically into `/var/backups/gyst-prod/`
before each push.
