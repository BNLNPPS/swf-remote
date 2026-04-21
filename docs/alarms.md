# swf-remote alarms

Always-on proactive alarm capability. Engine polls swf-monitor's REST
through swf-remote's own tunnel+proxy, persists everything in swf-remote's
Postgres via a generic **Entry** table that follows tjai's document-DB
pattern, delivers email via AWS SES (more channels — Mattermost, Telegram
— designed in but not yet wired). The dashboard lives on the prod header
menu, right of PCS; the per-alarm editor is CodeMirror with autosave and
version history.

## Why this shape

- **Standalone engine, not a Django management command.** See profile note
  `profile-standalone-over-django-mgmt-commands` — operational tools stay
  REST-fed, lightweight, and independent of one Django app's bootstrap.
- **One DB.** swf-remote already runs on Postgres; alarm state goes in the
  same DB. No sqlite, no second store.
- **Everything is an `Entry`.** The alarm config, each firing, each engine
  tick — all rows in the same tjai-faithful `entry` table. Adding a new
  customization on swf-remote (next project, whatever it is) = reuse the
  same table with a new `kind` value. `data` JSONField carries the
  per-kind metadata.
- **State-based dedup (not cooldown timers).** One active event per
  (alarm, entity); while that event exists the engine bumps its
  `data.last_seen` without re-emailing. When the condition goes away, the
  engine sets `data.clear_time = now`. Next time it re-appears, a new
  event (and a new email) fires.
- **Nav injection.** The alarm dashboard lives on the production header
  menu alongside PCS. swf-remote's own pages use a local base template;
  proxied swf-monitor pages (PanDA, PCS) get an `Alarms` link injected
  in `monitor_client.proxy()` the same way `nav-auth` is swapped.

## Architecture

```
  ┌──────────────────────┐
  │  swf-alarms engine   │  (cron */5 min)
  │  alarms/swf_alarms/  │
  │  standalone venv     │
  └───┬──────────────┬───┘
      │ https        │ psycopg
      │ (loopback)   │
      ▼              ▼
  ┌─────────────────────┐   ┌──────────────────────────┐
  │  swf-remote Django  │   │  Postgres (swf_remote)   │
  │  /prod/api/panda/*  │──►│  entry, entry_context,   │
  │  /prod/alarms/      │   │  entry_version           │
  └──────────┬──────────┘   └──────────────────────────┘
             │ SSH tunnel
             ▼
  ┌─────────────────────┐   ┌──────────────────────────┐
  │  swf-monitor (BNL)  │   │  AWS SES                 │
  │  /api/panda/tasks/… │   │  alarm emails            │
  └─────────────────────┘   └──────────────────────────┘
```

## Entry conventions used by alarms

All rows live in context `swf-alarms`. Rows are filtered out of live
views when `archived=True` (explicit boolean, separate from `status`).

| kind          | data.entry_id               | What it represents |
|---------------|------------------------------|--------------------|
| `alarm`       | `alarm_<name>`               | One configured alarm. `content` is the description / email body. `data.params` holds thresholds etc. `data.recipients` routes emails. `data.enabled` gates execution. |
| `event`       | `event_<name>` (NON-UNIQUE)  | One firing instance. Many rows share the same `entry_id`. `data.fire_time` set when created, `data.clear_time` null=active, set=cleared. `data.dedupe_key` identifies the entity (e.g. task id). `content` is the email body sent when this fired. |
| `engine_run`  | `run_<unix_ts>`              | One engine tick. `data` holds aggregate counters, per-check detail, any error trace. |

Multiple event rows share `data.entry_id` — that's deliberate. `entry_id`
identifies the alarm type; the Entry's UUID distinguishes instances.

## Engine loop (per tick)

1. Load `kind='alarm'` entries where `archived=False` and `data.enabled=true`.
2. For each alarm config:
   a. Fetch current active events (clear_time null) for this alarm.
   b. Run the check (PanDA REST call via swf-remote proxy). Collect
      `dedupe_key`s yielded this tick.
   c. For each detection:
      - `dedupe_key` in active-events map → bump `data.last_seen`, no email.
      - Otherwise → create a new `kind='event'` row (fire_time=now,
        clear_time=null), compose email body as
        `<alarm.content>\n\n---\n\n<detection body_context>`, send SES.
   d. For each previously-active event whose `dedupe_key` is NOT in this
      tick's detections (and the check didn't error), set
      `data.clear_time = now`. Auto-clear.
3. Close out the `engine_run` entry with counters + per-check summary.

Transient fetch failure on one check does NOT auto-clear that check's
active events — the last known state is preserved until the next
successful tick.

## Dashboard

At `/prod/alarms/`. Parts:

1. **Engine health banner** — ok / warn / bad / unknown, from last
   `engine_run` finished time and error count.
2. **Summary table** — one row per alarm config: name (link to section),
   severity, enabled, firings in last N hours (N user-settable, default
   24), currently-active count, last fired time.
3. **Per-alarm section** (one per active alarm config):
   - Header: name, severity pill, `[Edit]` button.
   - Metadata table: entry_id, kind, created/modified, recipients, params.
   - Body/description card.
   - Events-in-window table (reverse chron): fire, clear, state, dedupe
     key, subject (link to event detail).
4. **Recent engine runs table** — counters per run, errors highlighted.

## Editor — `/prod/alarms/<entry_id>/edit/`

CodeMirror 5 (markdown mode, material-darker theme) on the alarm's
`content` (description / email body). JSON-mode CodeMirror on
`enabled/severity/recipients/kind/params`. Features:

- **Autosave** every 10s via POST (JSON body). Also on Ctrl/Cmd-S,
  and on `beforeunload` via `navigator.sendBeacon`.
- **localStorage backup** on every keystroke. If the browser crashes or
  the server is unreachable, the backup is visible as a "local" row in
  the version-history table with a `[Restore]` button.
- **Version history table** — server-side versions (rendered inline on
  page load) with click-to-load. The server creates an `EntryVersion`
  row automatically via the `pre_save` signal whenever content or
  substantive `data` changes (noise keys like `last_seen` are filtered
  out so autosave doesn't spam version rows).

All server-side edits go through `alarm_views.alarm_config_save`; the
Entry's pre_save signal handles versioning transparently.

## Nav "Alarms" link

Right of PCS, on every production-mode page:

- **swf-remote native pages** (alarm dashboard, editor, event detail):
  `src/templates/base.html` has the link in the header nav directly.
- **Proxied swf-monitor pages** (PanDA, PCS, hubs): `monitor_client.proxy()`
  injects the link inside the `<span class="nav-mode nav-production">…</span>`
  block — same mechanism that swaps `nav-auth`.

## Files added / changed

Django side:

| File | Purpose |
|---|---|
| `src/remote_app/models.py` | `EntryContext`, `Entry`, `EntryVersion`. tjai-faithful fields; `archived` boolean; pinned `db_table` names. |
| `src/remote_app/migrations/0001_initial.py` | Schema. |
| `src/remote_app/migrations/0002_seed_alarms.py` | Seed `swf-alarms` context + two initial alarm configs (Sakib-only + EIC catch-all). Idempotent. |
| `src/remote_app/signals.py` | `pre_save` snapshot on Entry — writes `EntryVersion` rows when content or substantive data changes. Thread-local `set_changed_by`. |
| `src/remote_app/apps.py` | Registers signals on app ready. |
| `src/remote_app/alarms_data.py` | ORM query helpers used by views. |
| `src/remote_app/alarm_views.py` | `alarms_dashboard`, `alarm_event_detail`, `alarm_config_edit`, `alarm_config_save`, `alarm_config_version`. |
| `src/remote_app/views.py` | Re-exports alarm views; `panda_api_proxy` unchanged. |
| `src/remote_app/urls.py` | Alarm routes added. |
| `src/remote_app/templates/monitor_app/alarms.html` | Dashboard template. |
| `src/remote_app/templates/monitor_app/alarm_config_edit.html` | CodeMirror editor + autosave + versions UI. |
| `src/remote_app/templates/monitor_app/alarm_event_detail.html` | Single firing detail. |
| `src/remote_app/templatetags/swf_fmt.py` | `fmt_dt` (Eastern YYYYMMDD HH:MM:SS) and `state_class` (BigMon `*_fill`). Mirrors swf-monitor. |
| `src/remote_app/static/css/state-colors.css` | Symlink to swf-monitor's copy. |
| `src/remote_app/monitor_client.py` | `panda_api_proxy` support (service_user); Alarms-link injection in proxied HTML. |
| `src/templates/base.html` | Prod-style header nav + Alarms link right of PCS. |

Engine side (`alarms/`):

| File | Purpose |
|---|---|
| `swf_alarms/config.py` | TOML loader — engine-level settings + DB DSN (reads SWF_REMOTE_DB_* from swf-remote's .env by default). Alarm CONFIGS are in the DB, not here. |
| `swf_alarms/db.py` | psycopg layer over `entry`/`entry_context`/`entry_version`. Alarm-specific helpers: `list_alarm_configs`, `active_events_for_alarm`, `create_event`, `touch_event_last_seen`, `clear_event`, `start/finish_engine_run`. |
| `swf_alarms/checks/__init__.py` | REGISTRY + `Detection` dataclass. |
| `swf_alarms/checks/failure_rate.py` | First check — yields Detection per task exceeding computed_failurerate. |
| `swf_alarms/run.py` | Runner: loads configs from DB, drives active/clear semantics, writes events + engine_run entries. |
| `swf_alarms/notify.py` | Alarm dataclass + SES send. Channel failures log but never raise. |
| `deploy/install.sh` | venv + log dir. No DB files touched here — schema is owned by swf-remote migrations. |
| `deploy/crontab.example` | */5 min cadence. |
| `config.toml.example` | Engine, DB, email only. |
| `pyproject.toml` | `httpx`, `boto3`, `psycopg[binary]`. |

## Adding a new alarm

Option A: via the dashboard — `[New alarm]` button (future; not in MVP).

Option B (MVP): add an entry directly via a small data migration or a
Django shell. An alarm config is an Entry with `kind='alarm'`,
`context='swf-alarms'`, `data.entry_id='alarm_<name>'`, and
`data = {kind, enabled, severity, recipients, params}`. Then the engine
picks it up on its next tick.

## Adding a new check kind

1. `alarms/swf_alarms/checks/<your_kind>.py` exposing
   `def your_kind(client, params): yield Detection(dedupe_key, subject, body_context, extra_data)`.
2. Register it in `alarms/swf_alarms/checks/__init__.py` REGISTRY.
3. Create one or more alarm configs with `data.kind = 'your_kind'`.

Contract: the check must not notify, must not raise on transient failure,
and must set a stable `dedupe_key` per entity so state-based dedup works.

## Adding a new channel

Add `send_<channel>(alarm, **cfg) -> bool` in `notify.py`. Wire it into
`run.py` behind a per-alarm or global `channels` config knob. Failures
must return False (never raise) so one stuck channel doesn't cascade.

## Future work

- `[New alarm]` and `[Delete]` buttons in the dashboard.
- Mattermost channel (SES-parallel).
- Per-task-owner routing (lookup task username → recipient at event-create
  time; config recipients list becomes a fallback).
- Acknowledgement: ack button on active events to suppress notify without
  waiting for auto-clear.
- Time-bucket charts per alarm (events/hour over last N days).
