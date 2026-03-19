#!/bin/bash
# Set up swf-remote development environment.
# Creates symlinks to swf-monitor shared templates and validates dependencies.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"

# swf-monitor location (sibling repo)
SWF_MONITOR="${SWF_MONITOR:-$(dirname "$SCRIPT_DIR")/swf-monitor}"

echo "=== swf-remote dev setup ==="

# ── Validate swf-monitor ────────────────────────────────────────────────────

if [ ! -d "$SWF_MONITOR/src/monitor_app/templates/monitor_app" ]; then
    echo "ERROR: swf-monitor not found at $SWF_MONITOR"
    echo "Set SWF_MONITOR env var to the swf-monitor repo root."
    exit 1
fi

echo "swf-monitor: $SWF_MONITOR"

# ── Shared templates ────────────────────────────────────────────────────────

MONITOR_TEMPLATES="$SRC_DIR/monitor_templates"
LINK_TARGET="$SWF_MONITOR/src/monitor_app/templates/monitor_app"

mkdir -p "$MONITOR_TEMPLATES"

if [ -L "$MONITOR_TEMPLATES/monitor_app" ]; then
    CURRENT=$(readlink "$MONITOR_TEMPLATES/monitor_app")
    if [ "$CURRENT" = "$LINK_TARGET" ]; then
        echo "Templates symlink OK: monitor_app -> $LINK_TARGET"
    else
        echo "Updating templates symlink (was: $CURRENT)"
        rm "$MONITOR_TEMPLATES/monitor_app"
        ln -s "$LINK_TARGET" "$MONITOR_TEMPLATES/monitor_app"
        echo "Templates symlink: monitor_app -> $LINK_TARGET"
    fi
elif [ -e "$MONITOR_TEMPLATES/monitor_app" ]; then
    echo "ERROR: $MONITOR_TEMPLATES/monitor_app exists but is not a symlink."
    echo "Remove it and re-run."
    exit 1
else
    ln -s "$LINK_TARGET" "$MONITOR_TEMPLATES/monitor_app"
    echo "Templates symlink created: monitor_app -> $LINK_TARGET"
fi

# Symlink shared base templates (base.html lives in swf-monitor's top templates dir)
BASE_LINK="$MONITOR_TEMPLATES/base_monitor.html"
BASE_TARGET="$SWF_MONITOR/src/templates/base.html"
if [ -L "$BASE_LINK" ]; then
    echo "Base template symlink OK"
elif [ -f "$BASE_TARGET" ]; then
    ln -s "$BASE_TARGET" "$BASE_LINK"
    echo "Base template symlink created: base_monitor.html -> $BASE_TARGET"
fi

# ── Static files symlink ────────────────────────────────────────────────────

STATIC_LINK="$SRC_DIR/remote_app/static"
STATIC_TARGET="$SWF_MONITOR/src/monitor_app/static"

if [ -d "$STATIC_TARGET" ] && [ ! -e "$STATIC_LINK" ]; then
    ln -s "$STATIC_TARGET" "$STATIC_LINK"
    echo "Static files symlink created"
elif [ -L "$STATIC_LINK" ]; then
    echo "Static files symlink OK"
fi

# ── Python venv ─────────────────────────────────────────────────────────────

VENV="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV" ]; then
    echo "Creating Python venv..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip
    "$VENV/bin/pip" install -r "$SCRIPT_DIR/requirements/dev.txt"
    echo "Venv created and dependencies installed."
else
    echo "Venv exists: $VENV"
fi

echo ""
echo "=== Setup complete ==="
echo "Activate venv:  source $VENV/bin/activate"
echo "Run dev server: cd src && python manage.py runserver"
