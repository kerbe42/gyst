#!/usr/bin/env bash
# One-time setup: clone the dev tree at /opt/house-inventory into
# /opt/gyst-prod with its own virtualenv, its own data dir, and a
# prod-tuned rxconfig.py that binds Reflex to internal port 3002.
#
# Re-runnable: if /opt/gyst-prod already exists, this aborts so it doesn't
# clobber a live install. Use sync-to-prod.sh for ongoing updates.

set -euo pipefail

DEV_DIR="/opt/house-inventory"
PROD_DIR="/opt/gyst-prod"
PROD_USER="nope"        # user that runs the prod systemd unit
PROD_GROUP="nope"

if [[ $EUID -ne 0 ]]; then
    echo "Run as root (sudo bash $0)." >&2
    exit 1
fi

if [[ -e "$PROD_DIR" ]]; then
    echo "Refusing to overwrite existing $PROD_DIR." >&2
    echo "Remove it first if you really want a fresh clone, or run" >&2
    echo "sync-to-prod.sh for an incremental update." >&2
    exit 1
fi

echo "==> Cloning $DEV_DIR -> $PROD_DIR (excluding runtime artifacts)"
rsync -a \
    --exclude='.venv/' \
    --exclude='.web/' \
    --exclude='data/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.git/' \
    --exclude='deploy/' \
    "$DEV_DIR"/ "$PROD_DIR"/

echo "==> Seeding empty data/ directory"
mkdir -p "$PROD_DIR/data/photos" "$PROD_DIR/data/chore_photos" "$PROD_DIR/data/tls"
chmod 700 "$PROD_DIR/data"

echo "==> Installing prod rxconfig (port 3002 backend)"
cp "$DEV_DIR/deploy/rxconfig.prod.py" "$PROD_DIR/house_demo/rxconfig.py"

echo "==> Creating dedicated virtualenv at $PROD_DIR/.venv"
python3 -m venv "$PROD_DIR/.venv"
"$PROD_DIR/.venv/bin/pip" install --upgrade pip wheel
"$PROD_DIR/.venv/bin/pip" install -r "$PROD_DIR/requirements.txt"

echo "==> Initializing Reflex build (.web/)"
cd "$PROD_DIR/house_demo"
"$PROD_DIR/.venv/bin/reflex" init --template blank --loglevel warning || true
"$PROD_DIR/.venv/bin/reflex" export --frontend-only --no-zip --loglevel warning || true

echo "==> Setting ownership to $PROD_USER:$PROD_GROUP"
chown -R "$PROD_USER:$PROD_GROUP" "$PROD_DIR"

echo
echo "Done. Next steps:"
echo "  sudo cp $DEV_DIR/deploy/gyst-prod.service /etc/systemd/system/"
echo "  sudo cp $DEV_DIR/deploy/Caddyfile /etc/caddy/Caddyfile   # or merge"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable --now gyst-prod"
echo "  sudo systemctl reload caddy"
