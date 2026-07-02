#!/usr/bin/env bash
# Incremental push: rsync code from dev (/opt/house-inventory) to prod
# (/opt/gyst-prod), snapshot the pre-push state, then restart the prod
# service. Never touches prod's data/, .venv/, or .web/.

set -euo pipefail

DEV_DIR="/opt/house-inventory"
PROD_DIR="/opt/gyst-prod"
PROD_USER="nope"
PROD_GROUP="nope"
BACKUP_DIR="/var/backups/gyst-prod"

if [[ $EUID -ne 0 ]]; then
    echo "Run as root (sudo $0)." >&2
    exit 1
fi

if [[ ! -d "$PROD_DIR" ]]; then
    echo "$PROD_DIR doesn't exist. Run clone-to-prod.sh first." >&2
    exit 1
fi

# ---- Test gate: never ship unverified engine code -------------------------
# Stdlib-only suites, <1s. A wrong weight prescription to a solo lifter is the
# strongman module's worst case, so block the deploy on a red suite.
echo "==> Running strongman test suites (engine + db)"
if ! ( cd "$DEV_DIR" && PYTHONPATH=. "$DEV_DIR/.venv/bin/python" -m strongman.tests.test_engine \
         && PYTHONPATH=. "$DEV_DIR/.venv/bin/python" -m strongman.tests.test_db ); then
    echo "Strongman tests FAILED — aborting deploy (prod untouched)." >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
SNAPSHOT="$BACKUP_DIR/code-$STAMP.tgz"

echo "==> Snapshotting current prod code to $SNAPSHOT"
tar -czf "$SNAPSHOT" \
    --exclude='.venv' --exclude='.web' \
    --exclude="$(basename "$PROD_DIR")/data" \
    --exclude='__pycache__' \
    -C "$(dirname "$PROD_DIR")" "$(basename "$PROD_DIR")"

# Trim to last 10 snapshots.
ls -1t "$BACKUP_DIR"/code-*.tgz 2>/dev/null | tail -n +11 | xargs -r rm -f

echo "==> Rsync $DEV_DIR -> $PROD_DIR (code only)"
rsync -a --delete \
    --exclude='.venv/' \
    --exclude='.web/' \
    --exclude='/data/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.git/' \
    --exclude='deploy/' \
    --exclude='house_demo/rxconfig.py' \
    "$DEV_DIR"/ "$PROD_DIR"/

# Always re-stamp the prod rxconfig so port/env stays correct even if
# dev's rxconfig drifts.
cp "$DEV_DIR/deploy/rxconfig.prod.py" "$PROD_DIR/house_demo/rxconfig.py"

# Refresh installed dependencies in case requirements.txt changed.
echo "==> Refreshing prod virtualenv deps"
"$PROD_DIR/.venv/bin/pip" install -q -r "$PROD_DIR/requirements.txt"

# Wipe Python bytecode so stale .pyc files don't shadow the new code.
find "$PROD_DIR" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

chown -R "$PROD_USER:$PROD_GROUP" "$PROD_DIR"

echo "==> Restarting gyst-prod"
systemctl restart gyst-prod
sleep 2
systemctl --no-pager --lines=20 status gyst-prod || true

echo
echo "Push complete. Watch logs:  sudo journalctl -u gyst-prod -f"
echo "Roll back if needed:        sudo tar -xzf $SNAPSHOT -C $(dirname "$PROD_DIR")"
