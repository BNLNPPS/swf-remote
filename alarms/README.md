# swf-alarms

Standalone polling alarm engine for the swf ecosystem (PanDA, streaming
workflow). Zero Django coupling — reads PanDA data via REST (through
swf-remote's proxy, which owns the SSH tunnel to pandaserver02), persists
state in sqlite, sends email via AWS SES. The swf-remote Django app serves
a read-only dashboard that reads the same sqlite file.

## Why standalone

- The engine can run on any host with network access to swf-remote — no
  Django bootstrap, no project PYTHONPATH shenanigans, no management command.
- Lightweight deps (`httpx`, `boto3`) mean the venv is small and portable.
- The swf-remote Django side only *reads* alarm state to render a dashboard.
  It doesn't run checks, own the data, or import engine code.
- Extending the channel mix (Mattermost, Telegram, PagerDuty) = drop a
  function into `swf_alarms/notify.py` and wire it in `run.py`. No Django
  restart.

## Install

```bash
cd /home/admin/github/swf-remote/alarms
bash deploy/install.sh
```

This creates `.venv/`, copies `config.toml.example` → `config.toml` if absent,
creates `/var/lib/swf-alarms/` and `/var/log/swf-alarms/` with the right
group perms for the Django dashboard to read, and initialises the sqlite
state DB.

Edit `config.toml` (SES region, recipients, thresholds) before the first live run.

## Run

Dry-run (no emails):

```bash
.venv/bin/swf-alarms-run --config config.toml --dry-run -v
```

For real:

```bash
.venv/bin/swf-alarms-run --config config.toml -v
```

## Schedule

See `deploy/crontab.example` — every 5 minutes is the default.

## Data source

The engine hits `https://epic-devcloud.org/prod/api/panda/tasks/` —
swf-remote's transparent proxy onto swf-monitor at BNL. Adding new panels
of PanDA data (queues, jobs, errors) is a question of (a) swf-monitor
exposing another REST endpoint and (b) swf-remote routing it through the
existing `panda_api_proxy` catch-all. No engine change.

## Adding a new check

1. Drop `swf_alarms/checks/your_check.py` with a `def your_check(client, params)`
   generator yielding `Alarm(...)` objects.
2. Register it in `swf_alarms/checks/__init__.py` by adding the entry to
   `REGISTRY`.
3. Add a `[[checks]]` block to `config.toml` with `kind = "your_check"`.

Checks must not send notifications, must not raise on transient failures,
and should scope `dedupe_key` to the entity they alarm on (task id, queue
name, etc.) so cooldown works naturally.

## Adding a new channel

Add a `send_<channel>(alarm, **cfg) -> bool` function in `notify.py`. Wire
it into `run.py`'s `_persist_and_maybe_notify` with a `channels = [...]`
config knob on each check (or a global default). Failures must return
False (not raise) so one stuck channel can't cascade.

## Dedup and cooldown

- **Dedup key** = `(check_name, dedupe_key)`. First time seen: insert,
  fire. Subsequent runs: update `last_seen_at`; notify only when cooldown
  has expired.
- **Cooldown** is config (`cooldown_hours`). 24h default. Resets only on
  successful notification.
- **No auto-clear** yet — an alarm stays `active` until either the engine
  re-notifies (after cooldown) or someone marks it cleared in the dashboard.
  Time-based auto-clear ("not seen in N runs") is a future addition.

## Dashboard

Served by swf-remote Django at `/prod/alarms/`. Read-only sqlite read —
no Django model, no migration. Template lives in
`src/remote_app/templates/monitor_app/alarms.html`.
