#!/bin/bash
# Container start-up for SupplyChain IQ.
# 1. start Redis   2. write site config from env   3. install site on first boot, else migrate
# 4. optional demo data   5. optional worker/scheduler   6. gunicorn on $PORT
set -euo pipefail

BENCH=${BENCH_DIR:-/home/frappe/frappe-bench}
SITE=${FRAPPE_SITE:-iq.local}
PORT=${PORT:-8000}
cd "$BENCH"

need() { if [ -z "${!1:-}" ]; then echo "Missing required environment variable $1" >&2; exit 1; fi; }
for v in DB_HOST DB_NAME DB_USER DB_PASSWORD ADMIN_PASSWORD ENCRYPTION_KEY; do need "$v"; done
DB_PORT=${DB_PORT:-5432}
export PGSSLMODE=${PGSSLMODE:-require}   # Neon and most hosted Postgres require TLS

# Answer Render's port scan with a 503 "starting" page while install/migrate runs.
./env/bin/python - "$PORT" >/dev/null 2>&1 <<'PY' &
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><body style='font-family:sans-serif;padding:40px'><h2>SupplyChain IQ is starting up</h2><p>Please refresh in a minute.</p></body></html>"
        self.send_response(503); self.send_header("Content-Type", "text/html"); self.send_header("Retry-After", "30")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    do_HEAD = do_GET
    def log_message(self, *a): pass
HTTPServer(("0.0.0.0", int(sys.argv[1])), H).serve_forever()
PY
PLACEHOLDER_PID=$!
trap 'kill $PLACEHOLDER_PID 2>/dev/null || true' EXIT

redis-server --port 6379 --bind 127.0.0.1 --save "" --appendonly no --maxmemory 64mb \
  --maxmemory-policy allkeys-lru --daemonize yes >/dev/null

./env/bin/python - <<PY
import json, os
common = {
    "redis_cache": "redis://127.0.0.1:6379",
    "redis_queue": "redis://127.0.0.1:6379",
    "redis_socketio": "redis://127.0.0.1:6379",
    "default_site": "$SITE",
    "serve_default_site": True,
    "socketio_port": 9000,
    "webserver_port": int("$PORT"),
    "use_redis_auth": False,
}
host = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PUBLIC_URL")
if host:
    common["host_name"] = host
json.dump(common, open("sites/common_site_config.json", "w"), indent=1)
open("sites/currentsite.txt", "w").write("$SITE")
PY

site_config() {
  ./env/bin/python - <<PY
import json, os
cfg = {
    "db_type": "postgres",
    "db_host": os.environ["DB_HOST"],
    "db_port": int(os.environ.get("DB_PORT", 5432)),
    "db_name": os.environ["DB_NAME"],
    "db_user": os.environ["DB_USER"],
    "db_password": os.environ["DB_PASSWORD"],
    "encryption_key": os.environ["ENCRYPTION_KEY"],
}
path = "sites/$SITE/site_config.json"
# containers start empty: recreate the folders Frappe expects next to site_config.json
for sub in ("logs", "locks", "public/files", "private/files", "private/backups"):
    os.makedirs(os.path.join("sites/$SITE", sub), exist_ok=True)
existing = json.load(open(path)) if os.path.exists(path) else {}
existing.update(cfg)
json.dump(existing, open(path, "w"), indent=1)
PY
}

installed=$(./env/bin/python - <<'PY'
import os, psycopg2
conn = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", 5432),
    dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
conn.autocommit = True
cur = conn.cursor()
cur.execute("select count(*) from information_schema.tables where table_name='tabInstalled Application'")
done = False
if cur.fetchone()[0]:
    cur.execute("""select count(*) from "tabInstalled Application" where app_name='supplychain_iq'""")
    done = bool(cur.fetchone()[0])
if not done:
    cur.execute("select count(*) from pg_tables where schemaname='public'")
    if cur.fetchone()[0]:
        # an earlier first boot stopped half-way; no IQ data can exist yet, so start clean
        import sys
        print("Partial installation found: resetting schema", file=sys.stderr)
        cur.execute("drop schema public cascade")
        cur.execute("create schema public")
print("yes" if done else "no")
PY
)

if [ "$installed" = "no" ]; then
  echo "First boot: installing Frappe + SupplyChain IQ into $DB_NAME"
  rm -rf "sites/$SITE"
  bench new-site "$SITE" --db-type postgres --no-setup-db \
    --db-host "$DB_HOST" --db-port "$DB_PORT" --db-name "$DB_NAME" \
    --db-user "$DB_USER" --db-password "$DB_PASSWORD" \
    --admin-password "$ADMIN_PASSWORD" --install-app supplychain_iq
  site_config
else
  echo "Existing installation found: applying migrations"
  site_config
  bench --site "$SITE" migrate --skip-search-index
fi

if [ -n "${DEMO_PASSWORD:-}" ]; then
  bench --site "$SITE" execute supplychain_iq.setup.demo.create_demo || echo "Demo data step failed (continuing)"
fi

if [ "${ENABLE_BACKGROUND:-0}" = "1" ]; then
  bench --site "$SITE" enable-scheduler
  (bench worker --queue short,default,long >/tmp/worker.log 2>&1 &)
  (bench schedule >/tmp/schedule.log 2>&1 &)
fi

kill "$PLACEHOLDER_PID" 2>/dev/null || true
wait "$PLACEHOLDER_PID" 2>/dev/null || true
trap - EXIT

cd sites
export FRAPPE_SITE="$SITE" FRAPPE_SITES_PATH="$BENCH/sites"
exec ../env/bin/gunicorn \
  --bind "0.0.0.0:$PORT" \
  --workers "${WEB_WORKERS:-1}" --threads "${WEB_THREADS:-4}" --worker-class gthread \
  --timeout 120 --graceful-timeout 30 --max-requests 2000 --max-requests-jitter 200 \
  --access-logfile - --preload \
  supplychain_iq.deploy_wsgi:application
