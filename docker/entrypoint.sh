#!/usr/bin/env bash
# Container entrypoint:
#   1. Prime the data dirs Reflex/Caddy expect.
#   2. Seed the container's Caddy PKI with the HOST'S internal CA so
#      certs minted in here chain to a CA the user's browser already
#      trusts (matches what gyst-prod and gyst-dev present). Avoids
#      the SEC_ERROR_BAD_SIGNATURE that comes from running two
#      different internal CAs on the same hostname.
#   3. Start Caddy in the background.
#   4. Start Reflex in the foreground.
#   5. Forward SIGTERM/SIGINT so `docker stop` is graceful.
set -euo pipefail

DATA=/app/data
mkdir -p "$DATA/photos" "$DATA/caddy-data" "$DATA/caddy-config" "$DATA/reflex"

# ---- Seed shared internal CA (idempotent) ----------------------------------
# The compose file bind-mounts /var/lib/caddy/.local/share/caddy/pki/authorities/local/
# read-only at /host-caddy-ca/. We copy it into Caddy's expected storage
# path on first start, then never touch it again. Subsequent restarts
# find it already in place and skip.
CA_DST="$DATA/caddy-data/caddy/pki/authorities/local"
if [ ! -f "$CA_DST/root.crt" ] && [ -d /host-caddy-ca ] && [ -f /host-caddy-ca/root.crt ]; then
  echo "[gyst-docker] seeding shared internal CA from /host-caddy-ca"
  mkdir -p "$CA_DST"
  cp /host-caddy-ca/root.crt "$CA_DST/root.crt"
  cp /host-caddy-ca/root.key "$CA_DST/root.key"
  cp /host-caddy-ca/intermediate.crt "$CA_DST/intermediate.crt"
  cp /host-caddy-ca/intermediate.key "$CA_DST/intermediate.key"
  chmod 600 "$CA_DST"/*.key
elif [ -f "$CA_DST/root.crt" ]; then
  echo "[gyst-docker] shared CA already present in volume; reusing"
else
  echo "[gyst-docker] no /host-caddy-ca mount — Caddy will mint its own CA"
  echo "             (browser will show untrusted cert warning the first time)"
fi

# Reflex's bun + node cache.
export HOME=${HOME:-$DATA}

echo "[gyst-docker] starting Caddy on :10443"
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
CADDY_PID=$!

shutdown() {
  echo "[gyst-docker] received signal, shutting down"
  kill -TERM "$CADDY_PID" 2>/dev/null || true
  kill -TERM "$REFLEX_PID" 2>/dev/null || true
  wait
  exit 0
}
trap shutdown SIGTERM SIGINT

echo "[gyst-docker] starting Reflex (prod) on :3003"
cd /app/house_demo
reflex run --env prod --loglevel info &
REFLEX_PID=$!

wait -n "$CADDY_PID" "$REFLEX_PID"
echo "[gyst-docker] one of the child processes exited; shutting down"
shutdown
