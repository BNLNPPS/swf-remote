#!/usr/bin/env bash
# swf-alarms install — creates venv, installs package, prepares log dir.
# Alarm state lives in swf-remote's Postgres; schema is owned by
# swf-remote's Django migrations and applied by its deploy script, not here.
#
# Usage:  bash deploy/install.sh
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
VENV="$HERE/.venv"
CONFIG="$HERE/config.toml"
LOG_DIR="/var/log/swf-alarms"

echo "[swf-alarms install] repo dir:  $HERE"

if [ ! -d "$VENV" ]; then
    echo "[swf-alarms install] creating venv"
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -e "$HERE" >/dev/null

if [ ! -f "$CONFIG" ]; then
    echo "[swf-alarms install] no config.toml yet — copying config.toml.example"
    cp "$HERE/config.toml.example" "$CONFIG"
    echo "[swf-alarms install] edit $CONFIG before first run"
fi

sudo mkdir -p "$LOG_DIR"
sudo chown admin:admin "$LOG_DIR"
sudo chmod 775 "$LOG_DIR"

echo "[swf-alarms install] done."
echo "  venv:    $VENV"
echo "  config:  $CONFIG"
echo "  logs:    $LOG_DIR/"
echo
echo "Schema: swf-remote's migrations own alarm_run / alarm_check_run /"
echo "  alarm_firing / alarm_firing_event. Ensure they're applied:"
echo "  cd /home/admin/github/swf-remote/src &&"
echo "  /var/www/swf-remote/.venv/bin/python manage.py migrate remote_app"
echo
echo "Next:"
echo "  1. edit $CONFIG  (thresholds, recipients)"
echo "  2. one-shot test: $VENV/bin/swf-alarms-run --config $CONFIG --dry-run -v"
echo "  3. install cron:  see deploy/crontab.example"
