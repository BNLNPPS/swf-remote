# swf-alarms

Standalone polling alarm engine for the swf ecosystem (PanDA, streaming
workflow). Zero Django coupling — pulls PanDA data via REST (through
swf-remote's proxy, which owns the SSH tunnel to pandaserver02), persists
state in swf-remote's Postgres (same DB as the Django dashboard), sends
email via AWS SES.

Full system overview: see `../docs/alarms.md`. This README is the
engine-developer entry point.

## Why standalone

- Runs on any host with network access to swf-remote — no Django
  bootstrap, no project PYTHONPATH, no management command.
- Lightweight deps (`httpx`, `boto3`, `psycopg`) mean a small, portable
  venv.
- The Django side only *reads* alarm state to render dashboards.

## Install

```bash
cd /home/admin/github/swf-remote/alarms
bash deploy/install.sh
```

Creates `.venv/`, copies `config.toml.example` → `config.toml` if absent.

Edit `config.toml` (SES region, from address, DB DSN) before the first
live run.

## Run

Dry-run (writes state, suppresses email):

```bash
.venv/bin/swf-alarms-run --config config.toml --dry-run -v
```

For real:

```bash
.venv/bin/swf-alarms-run --config config.toml -v
```

## Schedule

See `deploy/crontab.example`. Every 5 minutes is the default cadence.

## Data source

The engine hits `https://epic-devcloud.org/prod/api/panda/tasks/` —
swf-remote's transparent proxy onto swf-monitor at BNL. Adding new
panels of PanDA data (queues, jobs, errors) is a question of (a)
swf-monitor exposing another REST endpoint and (b) swf-remote routing
it through the existing `panda_api_proxy` catch-all. No engine change
required.

## Adding a new alarm

See `../docs/alarms.md` § "Adding a new alarm" for the full mechanism.
Summary:

1. Drop `swf_alarms/alarms/<name>.py` exposing a `PARAMS` dict and
   `def detect(client, params)`, yielding `Detection(...)` objects.
2. Share math via `swf_alarms/lib/*` — no central registry.
3. Create an `Entry` row (kind='alarm', context='swf-alarms',
   data.entry_id matching the module name) via data migration or
   Django shell.
4. Next cron tick picks it up automatically.

The contract: `detect` must not email, must not raise on transient
fetch failures (log + yield nothing), and must set a stable
`dedupe_key` per entity so state-based dedup works.

## Adding a new channel

Add `send_<channel>(alarm, **cfg) -> bool` in `notify.py`. Wire into
`run.py` behind a `channels = [...]` config knob. Failures must return
False (not raise) so one stuck channel can't cascade.

## "Disabled" (per-alarm) semantics

Each alarm's `data.enabled` flag controls **only the email side**. When
False:

- The algorithm still runs every tick.
- Event rows are still created, and active/clear still ticks.
- The dashboard still shows everything.
- **No SES call is made.** `last_notified` is not updated.

When True, the engine additionally sends email on new detections and on
renotification. "Stop the algorithm entirely" is `archived=True`, not
`enabled=False`. There is no global email switch — per-alarm is the
only control.

## Dedup and renotification

- **State-based dedup.** One active `event` row per `(alarm, entity)`.
  While active, the engine bumps `data.last_seen` without re-emailing.
- **Auto-clear.** On a successful tick where the entity is no longer
  in the detection set, the event's `data.clear_time` is set to now.
  A transient fetch failure does NOT auto-clear — last-known state is
  preserved.
- **One email per alarm per tick.** Every detection that would warrant
  a send this tick (new events, plus events whose renotification
  window has elapsed, plus events created while emails were off) is
  bundled into a single SES email. No more one-email-per-task.
- **Renotification window.** Per-alarm `data.renotification_window_hours`.
  Governs when a still-firing event is eligible to be re-included in
  the next bundle. 0 / missing = one email per event lifecycle (the
  event is bundled once when new, never renotified until it clears and
  re-fires).

## Dashboard

Served by swf-remote Django at `/prod/alarms/`. Reads from the same
Postgres `entry` table the engine writes. See
`../src/remote_app/alarm_views.py`.
