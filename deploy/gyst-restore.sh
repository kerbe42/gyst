#!/usr/bin/env bash
# Restore a GYST data directory from a restic snapshot.
#
# Usage:
#   sudo gyst-restore.sh latest prod /opt/gyst-prod/data
#   sudo gyst-restore.sh <snapshot-id> dev /opt/house-inventory/data
#
# Lists snapshots if called with no args.

set -euo pipefail

set -a
. /etc/gyst-backup/env
set +a

if [[ $# -eq 0 ]]; then
    echo "Available snapshots:"
    restic snapshots
    echo
    echo "Usage: $0 <snapshot-id|latest> <tag:dev|prod> <target-path>"
    exit 0
fi

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 <snapshot-id|latest> <tag:dev|prod> <target-path>" >&2
    exit 1
fi

SNAPSHOT=$1
TAG=$2
TARGET=$3

if [[ ! -d "$TARGET" ]]; then
    echo "Target $TARGET doesn't exist; create it first or pick another path." >&2
    exit 1
fi

# Safety: don't blow away running prod data without warning.
SERVICE=""
[[ "$TARGET" == "/opt/gyst-prod/data" ]] && SERVICE="gyst-prod"
[[ "$TARGET" == "/opt/house-inventory/data" ]] && SERVICE="house-reflex"

if [[ -n "$SERVICE" ]]; then
    echo "About to overwrite $TARGET. The $SERVICE service should be stopped first."
    read -rp "Stop $SERVICE and proceed? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
    systemctl stop "$SERVICE"
fi

# Pre-restore backup of whatever is currently there.
STAMP=$(date +%Y%m%d-%H%M%S)
SAFETY="/var/backups/gyst-restore-safety/${TARGET//\//_}-$STAMP.tgz"
mkdir -p "$(dirname "$SAFETY")"
echo "Taking a safety snapshot of the current $TARGET -> $SAFETY"
tar -czf "$SAFETY" -C "$(dirname "$TARGET")" "$(basename "$TARGET")" || true

# Restore.
echo "Restoring snapshot=$SNAPSHOT tag=$TAG -> $TARGET"
restic restore "$SNAPSHOT" --target "/" --tag "$TAG" --include "$TARGET"

if [[ -n "$SERVICE" ]]; then
    echo "Starting $SERVICE"
    systemctl start "$SERVICE"
fi

echo
echo "Restore complete. Safety copy of pre-restore state: $SAFETY"
