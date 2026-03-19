#!/bin/bash
# Set up Apache vhost and Let's Encrypt for epic-devcloud.org.
# Run once after DNS A record points to this server.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
DEPLOY_DIR="/var/www/swf-remote"
SWF_MONITOR_DEV="/home/admin/github/swf-monitor"
SWF_MONITOR_PROD="/var/www/swf-monitor"
DOMAIN="epic-devcloud.org"

echo "=== Apache setup for $DOMAIN ==="

# ── Deploy directories ─────────────────────────────────────────────────────

for dir in "$DEPLOY_DIR" "$SWF_MONITOR_PROD"; do
    if [ ! -d "$dir" ]; then
        sudo mkdir -p "$dir"
        sudo chown admin:admin "$dir"
        echo "Created $dir"
    fi
done

# ── Rsync swf-monitor to production ────────────────────────────────────────

rsync -a --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.env' \
    "$SWF_MONITOR_DEV/" "$SWF_MONITOR_PROD/"
echo "swf-monitor synced to $SWF_MONITOR_PROD"

# ── Rsync swf-remote to production ─────────────────────────────────────────

rsync -a --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude 'src/.env' \
    --exclude 'staticfiles' \
    --exclude 'src/monitor_templates' \
    "$REPO_DIR/" "$DEPLOY_DIR/"
echo "swf-remote synced to $DEPLOY_DIR"

# ── Venv and deps ───────────────────────────────────────────────────────────

if [ ! -d "$DEPLOY_DIR/.venv" ]; then
    python3 -m venv "$DEPLOY_DIR/.venv"
fi
"$DEPLOY_DIR/.venv/bin/pip" install -q -r "$DEPLOY_DIR/requirements/prod.txt"
echo "Dependencies installed"

# ── Setup symlinks (templates, static from swf-monitor) ─────────────────────

export SWF_MONITOR="$SWF_MONITOR_PROD"
bash "$DEPLOY_DIR/setup-dev.sh"

# ── .env ────────────────────────────────────────────────────────────────────

if [ ! -f "$DEPLOY_DIR/src/.env" ]; then
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
    cat > "$DEPLOY_DIR/src/.env" <<EOF
SWF_REMOTE_SECRET_KEY=$SECRET_KEY
SWF_REMOTE_DEBUG=False
SWF_REMOTE_ALLOWED_HOSTS=$DOMAIN,www.$DOMAIN,localhost

SWF_REMOTE_DB_NAME=swf_remote
SWF_REMOTE_DB_USER=swf_remote
SWF_REMOTE_DB_PASSWORD=swf_remote
SWF_REMOTE_DB_HOST=localhost
SWF_REMOTE_DB_PORT=5432

SWF_REMOTE_STATIC_URL=/static/
SWF_REMOTE_MONITOR_URL=https://localhost:18443/swf-monitor
EOF
    echo ".env created"
else
    echo ".env exists"
fi

# ── Database ────────────────────────────────────────────────────────────────

bash "$DEPLOY_DIR/setup-server.sh"

# ── Collect static files ────────────────────────────────────────────────────

cd "$DEPLOY_DIR/src"
"$DEPLOY_DIR/.venv/bin/python" manage.py collectstatic --noinput
echo "Static files collected"

# ── Apache config ───────────────────────────────────────────────────────────

sudo cp "$DEPLOY_DIR/deploy/epic-devcloud.conf" /etc/apache2/sites-available/
sudo a2ensite epic-devcloud.conf
sudo systemctl reload apache2
echo "Apache configured and reloaded"

# ── SSL certificate ─────────────────────────────────────────────────────────

echo ""
echo "To add HTTPS (after DNS is pointing here):"
echo "  sudo certbot --apache -d $DOMAIN"
echo ""
echo "=== Setup complete ==="
echo "Site: http://$DOMAIN/"
