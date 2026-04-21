# swf-remote alarms

Always-on proactive alarm capability running on ec2dev, fed by swf-monitor
REST, persisted in sqlite, delivered by email (SES) today and designed to
bolt on Mattermost, Telegram, etc. without rework. The Django side (this
repo's `remote_app`) serves a read-only dashboard over the sqlite state
file; the engine itself lives in this repo's `alarms/` directory but has
**no Django coupling** — it's a standalone installable package that could
be moved to its own repo without code changes.

## Why this shape

- **Standalone engine, not a Django management command.** See profile
  note `profile-standalone-over-django-mgmt-commands` — operational tools
  should be portable, REST-fed, and lightweight, not wedded to one
  Django project's bootstrap.
- **All swf-monitor access flows through swf-remote's existing SSH tunnel
  and proxy.** The engine hits `/prod/api/panda/*` on loopback; it never
  reaches BNL directly. Running the same engine from another host requires
  only that it can reach a swf-remote-style proxy (or set up its own
  tunnel) — no BNL SSH-key provisioning needed per consumer.
- **Dedup + cooldown in sqlite.** Every detection is persisted; notifications
  are rate-limited per firing. `last_seen_at` updates every tick so the
  dashboard is always current, even when the email channel is quiet
  inside a cooldown window.
- **Dashboard reads sqlite directly** — no Django ORM, no migrations, no
  coupling. `SWF_ALARMS_DB` in settings points to the file; if it's
  missing (engine hasn't run), the dashboard degrades to an empty state.

## Architecture

```
  ┌──────────────────────┐
  │  swf-alarms engine   │  (cron */5 min)
  │  alarms/swf_alarms/  │
  │  standalone venv     │
  └──────────┬───────────┘
             │ https (loopback)
             ▼
  ┌──────────────────────┐   ┌─────────────────────────┐
  │  swf-remote Django   │   │  sqlite state DB        │
  │  /prod/api/panda/*   │   │  /var/lib/swf-alarms/   │
  │  /prod/alarms/       │◄──┤  state.db               │
  └──────────┬───────────┘   └───────▲─────────────────┘
             │ SSH tunnel                │ writes
             ▼                            │
  ┌──────────────────────┐   ┌─────────────────────────┐
  │  swf-monitor (BNL)   │   │  AWS SES                │
  │  /api/panda/tasks/…  │   │  alarm emails           │
  └──────────────────────┘   └─────────────────────────┘
```

## swf-remote side — what's added

| File | Purpose |
|---|---|
| `src/remote_app/views.py` → `panda_api_proxy` | Catch-all proxy for `/api/panda/<path>` that injects `X-Remote-User: swf-remote-proxy` service identity. |
| `src/remote_app/views.py` → `alarms_dashboard`, `alarms_detail` | Dashboard views (read-only sqlite). |
| `src/remote_app/alarms_reader.py` | Plain-sqlite3 helpers for dashboard views. No ORM. |
| `src/remote_app/templates/monitor_app/alarms.html` | Active-alarms table + recent runs. |
| `src/remote_app/templates/monitor_app/alarm_detail.html` | Single-firing detail with event log. |
| `src/remote_app/monitor_client.py` → `proxy(service_user=...)` | Optional fallback identity for unauthenticated proxy calls. |
| `src/remote_app/urls.py` | New routes: `api/panda/<path:path>`, `alarms/`, `alarms/<int:firing_id>/`. |
| `src/swf_remote_project/settings.py` → `SWF_ALARMS_DB` | Path to the sqlite state file. |

## Engine side — `alarms/`

Standalone Python package. Not imported by Django. Install instructions in
`alarms/README.md`. Key files:

| File | Purpose |
|---|---|
| `swf_alarms/config.py` | TOML config loader (stdlib tomllib). |
| `swf_alarms/db.py` | sqlite schema (firings, events, runs, check_runs), upsert with dedup. |
| `swf_alarms/fetch.py` | Thin REST client. Targets swf-remote's `/api/panda/*`. |
| `swf_alarms/notify.py` | `Alarm` dataclass + SES email sender. New channels slot in here. |
| `swf_alarms/checks/failure_rate.py` | First check: computed_failurerate > threshold. |
| `swf_alarms/checks/__init__.py` | `REGISTRY` — map check `kind` → function. |
| `swf_alarms/run.py` | Main entry point. Deterministic, idempotent, crash-safe. |
| `config.toml.example` | Recipient routing, thresholds, cooldowns. |
| `deploy/install.sh` | venv + perms + sqlite init. |
| `deploy/crontab.example` | */5 min schedule. |

## Data flow (one tick)

1. Cron invokes `swf-alarms-run --config /…/config.toml`.
2. Engine opens/creates sqlite state DB, starts a `runs` row.
3. For each configured check (enabled or not):
   - Fetch from swf-remote's REST proxy (paginated).
   - Yield `Alarm` objects per matching entity.
   - For each alarm: upsert into `firings` (dedupe by `(check_name, dedupe_key)`),
     log an event (`fired` / `re-confirmed` / `re-fired`), and — if not in
     cooldown — send via SES, then log `notified` or `notify-failed`.
   - Record a `check_runs` row: timing, how many alarms the check saw,
     whether it errored, a snapshot of its config params — this is what
     the dashboard's "Alarm sources" panel reads.
4. Finish the `runs` row with counters and (on error) a full traceback
   in `error_details`.

## Cooldown semantics

- Per-firing cooldown, set from the check's `cooldown_hours` (default 24h).
- Cooldown is reset only when a notification actually succeeds.
- In cooldown: detection still runs and `last_seen_at` updates each tick,
  but email is suppressed and an event `notify-skipped-cooldown` is logged.
- Out of cooldown: the next detection re-notifies with a fresh cooldown.

## Adding a check

1. Write `alarms/swf_alarms/checks/mycheck.py` exposing
   `def mycheck(client, params): yield Alarm(...)`.
2. Register in `alarms/swf_alarms/checks/__init__.py`.
3. Add a `[[checks]]` block to `config.toml` with `kind = "mycheck"`.

Checks must not notify, must not raise on transient failure, must set
`dedupe_key` at the right scope (one per entity). See the failure-rate
check as the reference shape.

## Adding a channel

Write `send_<channel>(alarm, **cfg) -> bool` in `notify.py`. Wire it into
`run.py`'s `_persist_and_maybe_notify` behind a per-check
`channels = [...]` or a global default. Failures must return False, not
raise — one stuck channel must not cascade.

## Dashboard

Served by swf-remote Django at `/prod/alarms/`. Read-only sqlite read —
no Django model, no migration. Every alarm email links here.

Layout:

1. **Overall health banner** (green/yellow/red/unknown). Computed from
   engine freshness (last run finished within 15 min?), last-run errors,
   and severity counts of active firings. This is the "is everything OK"
   signal at a glance.
2. **Summary cards** — active/total firing counts, severity breakdown,
   last engine run timing.
3. **Alarm sources** — one row per configured check, showing last run,
   alarms seen, errors, currently-active firings, last-fired time, and
   the check's configured params (severity, cooldown, recipients,
   thresholds). Answers "what's being monitored and how is each check
   doing". Error tracebacks appear inline under the failing check.
4. **Alarm firings** — the active/cleared/all table. Each row links
   to the detail page (metadata, email body, context data, event log).
5. **Recent engine runs** — per-run counters, errors highlighted.

Views: `remote_app/views.py` → `alarms_dashboard`, `alarms_detail`.
Templates: `remote_app/templates/monitor_app/alarms.html`,
`alarm_detail.html`. Read helpers: `remote_app/alarms_reader.py`
(plain sqlite3, read-only `file:?mode=ro` connection).

## Future work

- Auto-clear when an alarm hasn't been seen for N runs / H hours.
- Dashboard action buttons: ack, silence, clear.
- Mattermost channel.
- Per-task-owner routing (look up task username → recipient, so Sakib
  gets his own alarms and Torre gets catch-all).
- Health-of-the-alarm-engine alarm (meta): if no `runs` row in last 15
  minutes, surface on the dashboard and email.
