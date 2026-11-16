#!/usr/bin/env bash
# NovaCore HRIS bench bootstrap. Idempotent: safe to run on every container start.
#   first start : bench init -> get apps -> link NovaCore apps -> new site -> install -> seed -> build
#   later starts: link check -> migrate -> start
set -euo pipefail

SITE="${SITE_NAME:-novacore.localhost}"
BRANCH="${FRAPPE_BRANCH:-version-15}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-123}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
SEED_DEMO="${SEED_DEMO:-1}"
BENCH_DIR="/home/frappe/frappe-bench"
APPS_SRC="/workspace/novacore/apps"
CUSTOM_APPS=(novacore_ph novacore_integrations)

log() { echo -e "\n\033[1;34m[novacore]\033[0m $*"; }

# --- toolchain: Frappe v15 accepts Python 3.10-3.14 and Node >= 18 -----------
# Prefer the most tested combination for v15 (Python 3.12/3.11, Node 22/20);
# 3.14 is accepted by Frappe but too new for some of v15's pinned dependencies.
pick_python() {
	local v p
	for v in 3.12 3.11 3.10 3.13; do
		p=$(ls -d "$HOME"/.pyenv/versions/${v}.* 2>/dev/null | sort -V | tail -1 || true)
		[ -n "$p" ] && { echo "$p/bin/python"; return; }
	done
	echo "No Python 3.10-3.13 found in image (have: $(ls "$HOME"/.pyenv/versions 2>/dev/null | tr '\n' ' '))" >&2
	exit 1
}
pick_node() {
	local v pref
	for pref in v22 v20 v18; do
		for v in $(ls "$NVM_DIR/versions/node" 2>/dev/null | sort -V -r); do
			case "$v" in "$pref".*) echo "$v"; return ;; esac
		done
	done
	# fall back to whatever node is on PATH
	node --version
}
NODE_VER=$(pick_node)
export PATH="$NVM_DIR/versions/node/$NODE_VER/bin:$PATH"
PYTHON_BIN=$(pick_python)
log "Using $($PYTHON_BIN --version) and node $NODE_VER"

# The image's MariaDB 11.8 client requires TLS by default, but the MariaDB 10.6 server
# (per the deployment diagram) has no certificates. Traffic stays on the private
# compose network, so disable client TLS instead of failing every `mariadb` call.
cat >"$HOME/.my.cnf" <<'EOF'
[client]
skip-ssl
EOF

log "Waiting for MariaDB..."
until (echo >/dev/tcp/mariadb/3306) >/dev/null 2>&1; do sleep 2; done

# --- bench --------------------------------------------------------------------
cd /home/frappe
if [ ! -d "$BENCH_DIR/apps/frappe" ]; then
	log "Creating bench ($BRANCH)..."
	rm -rf "$BENCH_DIR"
	bench init --skip-redis-config-generation --skip-assets --frappe-branch "$BRANCH" \
		--python "$PYTHON_BIN" frappe-bench
fi
cd "$BENCH_DIR"

bench set-mariadb-host mariadb
bench set-redis-cache-host redis://redis:6379
bench set-redis-queue-host redis://redis:6379
bench set-redis-socketio-host redis://redis:6379
# redis runs in its own container; file watching is not needed
sed -i '/redis/d;/watch/d' ./Procfile

for app in erpnext hrms; do
	if [ ! -d "apps/$app" ]; then
		log "Getting $app ($BRANCH)..."
		bench get-app --branch "$BRANCH" --skip-assets "$app"
	fi
done

# --- NovaCore custom apps (symlinked so source edits are live) ---------------
[ -n "$(tail -c1 sites/apps.txt)" ] && echo >>sites/apps.txt
for app in "${CUSTOM_APPS[@]}"; do
	[ -e "apps/$app" ] || ln -s "$APPS_SRC/$app" "apps/$app"
	if ! ./env/bin/python -c "import $app" 2>/dev/null; then
		log "Installing python package $app..."
		./env/bin/pip install --quiet -e "apps/$app"
	fi
	grep -qx "$app" sites/apps.txt || echo "$app" >>sites/apps.txt
done

# --- site ---------------------------------------------------------------------
# A site counts as installed only after every app is installed (marker file).
# A leftover folder from an interrupted install is recreated, never migrated.
INSTALLED_MARKER="sites/$SITE/.novacore_installed"
if [ -d "sites/$SITE" ] && [ ! -f "$INSTALLED_MARKER" ]; then
	log "Found incomplete site $SITE from an interrupted install - recreating it"
	rm -rf "sites/$SITE"
fi

if [ ! -d "sites/$SITE" ]; then
	log "Creating site $SITE..."
	bench new-site "$SITE" \
		--force \
		--mariadb-root-password "$DB_ROOT_PASSWORD" \
		--admin-password "$ADMIN_PASSWORD" \
		--no-mariadb-socket
	bench --site "$SITE" set-config developer_mode 1
	bench --site "$SITE" set-config host_name "http://localhost:8000"
	log "Installing apps..."
	bench --site "$SITE" install-app erpnext
	bench --site "$SITE" install-app hrms
	bench --site "$SITE" install-app novacore_ph
	bench --site "$SITE" install-app novacore_integrations
	touch "$INSTALLED_MARKER"
else
	log "Migrating $SITE..."
	bench --site "$SITE" migrate
fi
bench use "$SITE"

if [ "$SEED_DEMO" = "1" ] && [ ! -f "sites/$SITE/.novacore_seeded" ]; then
	log "Seeding demo data..."
	if bench --site "$SITE" execute novacore_ph.setup.demo.run; then
		touch "sites/$SITE/.novacore_seeded"
	else
		log "WARNING: demo seeding failed - check the output above. It will be retried on next start."
	fi
fi
bench --site "$SITE" enable-scheduler

if [ ! -f sites/assets/assets.json ] || [ ! -e sites/assets/novacore_ph ] || [ "${BUILD_ASSETS:-0}" = "1" ]; then
	log "Building assets (several minutes)..."
	bench build
fi
bench --site "$SITE" clear-cache

log "Ready: http://localhost:8000"
exec bench start
