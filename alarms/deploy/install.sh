#!/usr/bin/env bash
# swf-alarms install — creates venv, installs package, initialises the
# sqlite state DB, and prepares log dirs. Safe to re-run.
#
# Usage:  bash deploy/install.sh
# Run from the alarms/ directory (or any — it resolves its own location).
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
VENV="$HERE/.venv"
CONFIG="$HERE/config.toml"
STATE_DIR="/var/lib/swf-alarms"
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

sudo mkdir -p "$STATE_DIR" "$LOG_DIR"
# The dashboard (swf-remote Django under www-data) reads the state DB.
# Make the DB admin-owned but www-data-readable via group.
sudo chown admin:www-data "$STATE_DIR" "$LOG_DIR"
sudo chmod 2775 "$STATE_DIR" "$LOG_DIR"

"$VENV/bin/swf-alarms-initdb" "$STATE_DIR/state.db"
# DB file itself: admin writes, www-data reads.
sudo chown admin:www-data "$STATE_DIR/state.db"
sudo chmod 660 "$STATE_DIR/state.db"

echo "[swf-alarms install] done."
echo "  venv:     $VENV"
echo "  config:   $CONFIG"
echo "  state:    $STATE_DIR/state.db"
echo "  logs:     $LOG_DIR/"
echo
echo "Next:"
echo "  1. edit $CONFIG  (SES region, recipients, thresholds)"
echo "  2. one-shot test:  $VENV/bin/swf-alarms-run --config $CONFIG --dry-run -v"
echo "  3. install cron:   see deploy/crontab.example"
