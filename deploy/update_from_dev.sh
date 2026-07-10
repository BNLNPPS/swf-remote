#!/usr/bin/env bash
# Sync swf-remote to /var/www/swf-remote, collectstatic, reload apache
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
TARGET_DIR=/var/www/swf-remote
VENV=$TARGET_DIR/.venv

rsync -av \
  --exclude '.venv' --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' --exclude '.env' \
  "$REPO_ROOT/" "$TARGET_DIR/"

find "$TARGET_DIR" -path "$TARGET_DIR/.venv" -prune -o -type f -exec sudo chmod a+rw {} \; -o -type d -exec sudo chmod a+rwx {} \;

"$VENV/bin/python" "$TARGET_DIR/src/manage.py" collectstatic --noinput

# Touch WSGI script to trigger mod_wsgi daemon process reload
touch "$TARGET_DIR/src/swf_remote_project/wsgi_subpath.py"

sudo systemctl reload apache2
echo "Deployment complete. Apache reloaded."
