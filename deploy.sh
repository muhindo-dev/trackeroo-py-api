#!/usr/bin/env bash
# Truckeroo production deploy — pull latest, migrate, seed, restart, verify.
# Run on the VPS (Webuzo terminal or SSH). Safe to re-run (idempotent).
set -e

echo "==> Locating app directory…"
# HARDCODED, deliberately. This VPS is shared with U-LITS, which has its own
# Python app at /var/www/etag-web-py containing its own migrate.py. The old
# `find … -name migrate.py | head -1` matched BOTH and picked whichever the
# filesystem happened to return first — one unlucky ordering away from running
# `git reset --hard` and `migrate.py seed` against the neighbour's live
# database. Never reintroduce a search step here.
APP=${APP:-/var/www/truckfully.com/app}
if [ ! -f "$APP/migrate.py" ]; then
  echo "ERROR: $APP/migrate.py not found. Set APP=… explicitly."; exit 1
fi
case "$APP" in
  *truckfully*) ;;
  *) echo "ERROR: refusing to deploy to '$APP' — not a truckfully path."; exit 1 ;;
esac
echo "    App: $APP"
cd "$APP"

echo "==> Backing up current DB (best-effort)…"
mkdir -p backups
if [ -f .env ]; then
  DBU=$(grep -E '^DB_USERNAME=' .env | cut -d= -f2-)
  DBP=$(grep -E '^DB_PASSWORD=' .env | cut -d= -f2-)
  DBN=$(grep -E '^DB_DATABASE=' .env | cut -d= -f2-)
  mysqldump -u"$DBU" -p"$DBP" "$DBN" > "backups/predeploy_$(date +%F_%H%M%S).sql" 2>/dev/null \
    && echo "    DB backed up." || echo "    (DB backup skipped)"
fi

echo "==> Pulling latest code…"
git fetch origin main && git reset --hard origin/main

echo "==> Selecting python…"
PY=python3
[ -x venv/bin/python ] && PY=venv/bin/python
[ -x .venv/bin/python ] && PY=.venv/bin/python
echo "    Using: $PY"

echo "==> Ensuring NGN currency in .env…"
if [ -f .env ]; then
  grep -q '^FLW_CURRENCY=' .env && sed -i 's/^FLW_CURRENCY=.*/FLW_CURRENCY=NGN/' .env || echo 'FLW_CURRENCY=NGN' >> .env
fi

echo "==> Running migrations + seed…"
$PY migrate.py migrate
$PY migrate.py seed

echo "==> Restarting the app service…"
# HARDCODED, like APP above and for the same reason. The old lookup grepped
# systemd for anything matching truck|track|negoride|gunicorn and took head -1.
# This VPS has BOTH truckfully.service (this app, /var/www/truckfully.com/app)
# and negoride.service (a different live app at negoride.ugnews24.info), so the
# match order decided which one got restarted — on at least one deploy it
# bounced negoride and left truckfully running stale code. Never grep for the
# service here.
SVC=${SVC:-truckfully.service}
if ! systemctl list-unit-files "$SVC" >/dev/null 2>&1; then
  echo "ERROR: $SVC not found. Set SVC=... explicitly."; exit 1
fi
SVC_DIR=$(systemctl show "$SVC" -p WorkingDirectory --value 2>/dev/null)
if [ -n "$SVC_DIR" ] && [ "$SVC_DIR" != "$APP" ]; then
  echo "ERROR: $SVC runs from '$SVC_DIR' but we deployed to '$APP'. Refusing."; exit 1
fi
echo "    systemctl restart $SVC"
systemctl restart "$SVC"

echo "==> Verifying endpoints (give it a few seconds)…"
sleep 4
for ep in vehicle-categories subscription-plans; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "https://truckfully.com/api/$ep")
  echo "    /api/$ep -> $code"
done
echo "==> Done. Expect 200s above (404 = service not restarted; check the gunicorn service)."
