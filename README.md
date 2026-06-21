# swf-remote

External PanDA production monitoring frontend for the ePIC experiment
at the Electron Ion Collider. Provides open-internet access to PanDA
monitoring services that live behind BNL's firewall.

**Live at https://epic-devcloud.org/**

## Architecture

```
Browser → epic-devcloud.org (Django/Apache)
              ↓ proxy (full rendered HTML)
          SSH tunnel (autossh, persistent)
              ↓
          swf-monitor (BNL) → PanDA database
```

- **Web pages** — the hub, all PanDA views, and all PCS views — are
  proxied as full rendered HTML from swf-monitor through the SSH tunnel
  (`remote_app/monitor_client.proxy`), which rewrites swf-monitor URLs to
  local `/prod/` paths and swaps in local auth controls. Same URL
  structure. Only swf-remote's own pages render locally (see
  *Local vs proxied pages*).
- **MCP server** (planned) re-exposes PanDA data for LLM access
  outside BNL, using thin REST endpoints on swf-monitor.
- **No local PanDA data** — all data comes from swf-monitor in real time.

## Sister projects

- [swf-monitor](https://github.com/BNLNPPS/swf-monitor) — Django web
  service at BNL with PanDA DB access, REST API, MCP server
- [swf-testbed](https://github.com/BNLNPPS/swf-testbed) — Streaming
  workflow testbed orchestration and agents
- [swf-common-lib](https://github.com/BNLNPPS/swf-common-lib) — Shared
  utilities for SWF agents

## Pages

| Path | Description |
|------|-------------|
| `/` | PanDA Hub — links to all monitoring views |
| `/panda/activity/` | Activity overview — job/task counts by status, user, site |
| `/panda/jobs/` | Job list with DataTables filtering and search |
| `/panda/jobs/<pandaid>/` | Job detail — full record, files, errors, log URLs |
| `/panda/tasks/` | JEDI task list with DataTables filtering |
| `/panda/tasks/<taskid>/` | Task detail with constituent jobs |
| `/panda/errors/` | Error summary — top patterns ranked by frequency |
| `/panda/diagnostics/` | Failed jobs with full error details |

## Setup

### Development

```bash
# Clone both repos side by side
git clone https://github.com/BNLNPPS/swf-remote.git
git clone https://github.com/BNLNPPS/swf-monitor.git

# Set up dev environment (venv, symlinks to swf-monitor templates)
cd swf-remote
bash setup-dev.sh

# Set up database and .env
bash setup-server.sh

# Run dev server
cd src && ../.venv/bin/python manage.py runserver
```

### Production

```bash
# Full deploy: rsync, venv, deps, symlinks, migrations, Apache, SSL
bash deploy/setup-apache.sh

# SSL (after DNS is pointing to the server)
sudo certbot --apache -d epic-devcloud.org
```

### SSH tunnel

The tunnel is managed by systemd via autossh. See
`deploy/swf-remote-tunnel.service`. Requires SSH key access from
the hosting server to swf-monitor's host via an SSH gateway.

```bash
sudo cp deploy/swf-remote-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now swf-remote-tunnel
sudo systemctl status swf-remote-tunnel
```

## Stack

- Django 5.2 (Python 3.11) — upgrading to Django 6.0 / Python 3.12
  after OS upgrade
- PostgreSQL (local, for Django internals only)
- Apache + mod_wsgi
- httpx for upstream REST calls
- autossh + systemd for persistent SSH tunnel
- Let's Encrypt for HTTPS

## Configuration

Environment variables prefixed `SWF_REMOTE_` to avoid collisions with
other apps on the same server. See `.env.example`.

## Local vs proxied pages

Most pages — the hub, all PanDA views, Alarms, and all PCS views — are served as
full rendered HTML proxied from swf-monitor (`remote_app/views.py`), so
they carry swf-monitor's own templates, nav, and styling. swf-remote
renders a smaller set itself, all using its own `base.html` (the dark nav
bar): the account page and the login / password-change pages. Alarm code
from the old local implementation remains in the tree for rollback/reference,
but live `/prod/alarms/...` pages proxy to swf-monitor.

The proxy (`monitor_client.proxy`) preserves swf-monitor's page body and
`<style>`, rewriting only URLs and the auth controls — so swf-monitor's
own nav and styling reach the browser intact on proxied pages.

swf-remote keeps a symlink to swf-monitor's templates (created by
`setup-dev.sh`) for the shared assets the local pages pull in. URL names
use `app_name = 'monitor_app'` so `{% url %}` tags resolve to swf-remote's
own routes.
