#!/usr/bin/env bash
# Daily backup of GYST data directories (dev + prod) using restic.
#
# Snapshots both /opt/house-inventory/data and /opt/gyst-prod/data with a
# tag per source. Prunes to keep:
#   - 7 daily snapshots
#   - 4 weekly snapshots
#   - 3 monthly snapshots
#
# Configuration lives in /etc/gyst-backup/env (RESTIC_REPOSITORY etc.).
# To send backups offsite later, edit RESTIC_REPOSITORY there — the rest
# of the pipeline (this script, the systemd timer) doesnt change.

set -euo pipefail

# Load env: RESTIC_REPOSITORY, RESTIC_PASSWORD_FILE, (optionally) AWS_*,
# B2_*, etc. for offsite backends.
set -a
. /etc/gyst-backup/env
set +a

log() { logger -t gyst-backup -- "$*"; echo "[gyst-backup] $*"; }

log "starting backup -> $RESTIC_REPOSITORY"

# Back up dev data.
if [[ -d /opt/house-inventory/data ]]; then
    log "snapshotting dev"
    restic backup \
        --tag dev \
        --exclude '*.tmp' --exclude '*.lock' --exclude '*-journal' \
        /opt/house-inventory/data
fi

# Back up prod data.
if [[ -d /opt/gyst-prod/data ]]; then
    log "snapshotting prod"
    restic backup \
        --tag prod \
        --exclude '*.tmp' --exclude '*.lock' --exclude '*-journal' \
        /opt/gyst-prod/data
fi

# Retention.
log "applying retention policy"
restic forget --prune \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 3

# Health check.
log "verifying repository integrity"
restic check --read-data-subset=5%

log "backup complete"
