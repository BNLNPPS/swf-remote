# swf-remote alarms

Always-on proactive alarm capability for the ePIC PanDA production. A
small standalone engine polls swf-monitor via swf-remote's loopback
proxy every five minutes, persists everything in swf-remote's Postgres
via a generic `Entry` table (tjai-style document-store), and ships email
through AWS SES. The dashboard lives on the prod header menu, right of
PCS; the per-alarm editor is CodeMirror with autosave and version history.

## Vocabulary

We use **three** distinct terms. They are not synonyms.

| Term                   | Meaning                                                                                                     | Scope |
|------------------------|-------------------------------------------------------------------------------------------------------------|-------|
| **Alarm**              | One configured condition — a module + a row in the DB + recipients. Fires **events** when matched.          | System noun. Never "check". |
| **Renotification window** | On a still-firing alarm, how long to wait before re-emailing the same entity. 0 = one email per lifecycle. | Per-alarm attribute. |
| **Since** (N hours / N days) | How far back to look. Two independent uses: the dashboard filter ("show events from the last N hours"), and the check's data lookback ("analyse PanDA jobs from the last N days"). Same word, different referents. | One is dashboard state; the other is per-alarm `params.since_days`. |

## What "disabled" means (per-alarm)

Each alarm has a per-alarm `data.enabled` flag, surfaced in the editor
as **Emails ON/OFF** and on the dashboard as the **Emails** column.

**`enabled=True` (Emails ON):** the algorithm runs every tick, events
fire into the DB, active/clear ticks, and emails are sent on new
detections (and on renotification when the window elapses).

**`enabled=False` (Emails OFF):** the algorithm **still runs every
tick**. Events **still** fire into the DB. Active/clear **still**
ticks. The dashboard **still** shows everything. **Only email delivery
is suppressed.** No SES call is made. `last_notified` is not touched.
The alarm is "silent" — monitoring stays operational, mail stops.

This is the intended flow for tuning a new or noisy alarm: turn it on,
watch the dashboard, confirm the detections look right, then flip
Emails ON.

**Stopping an alarm entirely** (algorithm does not run at all) is
`archived=True`. That also hides the row from the live dashboard.
`archived` is separate from `enabled`.

There is **no global emails switch.** Per-alarm is the only control.

## Why this shape

- **Standalone engine, not a Django management command.** See profile
  note `profile-standalone-over-django-mgmt-commands` — operational
  tools stay REST-fed, lightweight, and independent of one Django app's
  bootstrap.
- **One DB.** swf-remote already runs on Postgres; alarm state goes in
  the same DB. No sqlite, no second store.
- **Everything is an `Entry`.** The alarm config, each firing, each
  engine tick — all rows in the same tjai-faithful `entry` table.
  Adding a new customization on swf-remote (next project, whatever it
  is) = reuse the same table with a new `kind` value. `data` JSONField
  carries the per-kind metadata.
- **Snowflake per alarm — no registry, no "kinds".** Each alarm has its
  own Python module at `alarms/swf_alarms/alarms/<name>.py` exposing
  `detect(client, params)`. The engine dispatches by importing the
  module whose name matches the alarm's entry_id. If two alarms share
  code, they share it by importing the same helper out of
  `alarms/swf_alarms/lib/`, not by being entries in a central dispatch
  table.
- **State-based dedup (not cooldown timers).** One active event per
  (alarm, entity); while that event exists the engine bumps its
  `data.last_seen` without re-emailing (unless the per-alarm
  renotification window has elapsed). When the condition goes away, the
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

All rows live in context `swf-alarms` (except teams, which live in
`teams`). Rows are filtered out of live views when `archived=True`
(explicit boolean, separate from `status`).

| kind          | data.entry_id               | What it represents |
|---------------|------------------------------|--------------------|
| `alarm`       | `alarm_<name>`               | One configured alarm. `content` is the description / email body. `data.params` holds thresholds etc. `data.recipients` routes emails. `data.enabled` gates **email delivery only** — the algorithm always runs. `data.renotification_window_hours` controls re-email. |
| `event`       | `event_<name>` (NON-UNIQUE)  | One firing instance. Many rows share the same `entry_id`. `data.fire_time` set when created, `data.clear_time` null=active, set=cleared. `data.dedupe_key` identifies the entity (e.g. task id). `content` is the email body sent when this fired. |
| `engine_run`  | `run_<unix_ts>`              | One engine tick. `data` holds aggregate counters, `data.per_alarm` carries per-alarm detail, any error trace. |

Multiple event rows share `data.entry_id` — that's deliberate. `entry_id`
identifies the alarm type; the Entry's UUID distinguishes instances.

## Alarm config `data` shape

Top-level keys on `data` are engine-universal (same for every alarm):

- `entry_id`       — `alarm_<name>`, matches the module filename.
- `enabled`        — boolean. Per-alarm **email switch**. When False
                     the algorithm still runs and events still fire —
                     only email delivery is suppressed. See "What
                     'disabled' means" above.
- `recipients`     — string or list; emails and/or `@team` references.
- `renotification_window_hours` — float; 0 means one email per lifecycle.
- `params`         — nested dict; **per-alarm** keys consumed by that
                     alarm's `detect()`. The alarm module declares its
                     PARAMS surface (see below).

## Engine loop (per tick)

1. Load `kind='alarm'` entries where `archived=False` **regardless of
   `data.enabled`**. The algorithm always runs; `enabled` only controls
   the email side.
2. For each alarm config:
   a. Fetch current active events (clear_time null) for this alarm.
   b. Import `swf_alarms.alarms.<name>` and call its `detect(client, params)`.
   c. For each detection:
      - `dedupe_key` in active-events map → bump `last_seen`. If this
        alarm's emails are on AND (the event has never been notified
        OR the renotification window has elapsed since `last_notified`),
        add it to this alarm's **renotify bundle**.
      - Otherwise → create a new `kind='event'` row (fire_time=now,
        clear_time=null), store a single-detection body on it (the
        event-detail page reads from this), and add it to this alarm's
        **new bundle**.
   d. For each previously-active event whose `dedupe_key` is NOT in
      this tick's detections (and the alarm didn't error), set
      `data.clear_time = now`. Auto-clear (unconditional of `enabled`).
3. If this alarm's emails are on AND the bundle is non-empty: ship **one
   SES email** covering all new + renotifying detections. On success,
   stamp `last_notified = now` on every event included in the bundle.
   `notifications_sent` in the engine-run counters increments by one
   per bundle, regardless of how many detections the bundle carried.
4. Close out the `engine_run` entry with counters + `data.per_alarm`
   (which includes `bundle_new`, `bundle_renotify`, `bundle_sent`).

**One email per alarm per tick**, never one-per-detection. When a tick
tripped N tasks, you receive a single email listing all N — not N
emails.

Transient fetch failure on one alarm does NOT auto-clear that alarm's
active events — the last known state is preserved until the next
successful tick.

## Dashboard

At `/prod/alarms/`. Parts:

1. **Engine health banner** — ok / warn / bad / unknown, from last
   `engine_run` finished time and error count. Shows seconds until the
   next */5 boundary.
2. **Teams** — reusable recipient aliases. `@<teamname>` references
   expand to member emails at send time. Editor is its own page.
3. **Summary table** — one row per alarm config: name (link to section),
   enabled, alarms-since-N-hours (N user-settable via the
   `Since` filter, default 24), currently-active count, last-fired
   time. A yellow **quiet** badge appears next to alarm names that saw
   zero detections in the last few runs despite prior history — a
   heuristic for silently-broken alarms.
4. **Per-alarm section** (one per active alarm config):
   - Header: name, `[Edit]` button.
   - Metadata table: entry_id, created/modified, recipients, params.
   - Body/description card.
   - Events-since-N-hours table (reverse chron): fire, clear, state,
     dedupe key, subject (link to event detail).
5. **Recent engine runs table** — counters per run, per-alarm
   breakdown, errors highlighted.

## Editor — `/prod/alarms/<entry_id>/edit/`

CodeMirror 5 (markdown mode, material-darker theme) on the alarm's
`content` (description / email body). JSON-mode CodeMirror on
`params`. First-class form fields for enabled, recipients,
renotification window.

Features:

- **PARAMS help panel** — the alarm module declares a `PARAMS` dict
  (name → type / required / default / description); the editor renders
  it as a table above the JSON box so you can see what keys this
  specific alarm actually reads.
- **[Test (live, no email)]** — runs the alarm's `detect()` once with
  the current in-editor params against live data, shows all detections
  in-page. Never emails. Uses the editor's unsaved values so you can
  try before saving.
- **[Preview email body]** — composes the email body (description +
  a synthetic detection context) so you can see what a real notification
  would look like.
- **Autosave** every 10s via POST (JSON body). Also on Ctrl/Cmd-S, and
  on `beforeunload` via `navigator.sendBeacon`.
- **localStorage backup** on every keystroke. If the browser crashes
  or the server is unreachable, the backup is visible as a "local" row
  in the version-history table with a `[Restore]` button.
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
- **Proxied swf-monitor pages** (PanDA, PCS, hubs):
  `monitor_client.proxy()` injects the link inside the
  `<span class="nav-mode nav-production">…</span>` block — same
  mechanism that swaps `nav-auth`.

## Adding a new alarm

There is no "new alarm" button in the UI — alarms are algorithms over
data, not configuration-only records. Adding one is a code + DB + cron
operation by a developer. The mechanism, end to end:

1. **Write the module.** Create
   `alarms/swf_alarms/alarms/<name>.py` exposing:

   ```python
   from ..lib import Detection

   PARAMS = {
       "threshold": {"type": float, "required": True,
                     "description": "fire when X exceeds this"},
       "since_days": {"type": int, "default": 1,
                      "description": "look back this many days"},
   }

   def detect(client, params):
       # ... query data via `client`, yield Detection(...) per entity ...
       yield Detection(
           dedupe_key="…",  # stable per-entity
           subject="…",     # email subject + dashboard row
           body_context="…",# appended to the alarm's description
           extra_data={},   # structured context for the event row
       )
   ```

   The contract: `detect` must not email, must not raise on transient
   failures (log and yield nothing), and must set a stable `dedupe_key`
   per entity so state-based dedup works.

2. **Share helpers, not dispatch.** If the algorithm is similar to an
   existing one, import a helper from `alarms/swf_alarms/lib/`. Do
   **not** add a central registry entry — there is no registry.

3. **Create the DB config.** Add an `Entry` row via a data migration
   (preferred: reproducible) or Django shell. Schema:

   ```python
   Entry(
       kind='alarm',
       context=<EntryContext name='swf-alarms'>,
       title="Human-readable title",
       content="Description that prefixes the email body…",
       data={
           'entry_id': 'alarm_<name>',          # must match module
           'enabled': True,
           'recipients': ['@prodops', 'alice@example.com'],
           'renotification_window_hours': 24,
           'params': { ... keys from PARAMS ... },
       },
       status='active',
       archived=False,
   )
   ```

4. **Pick it up on the next tick.** The engine runs every 5 minutes
   via cron (`alarms/deploy/crontab.example`). New modules are picked
   up automatically by the next tick — no engine restart required, no
   redeploy required. If you want to run it immediately:

   ```bash
   /home/admin/github/swf-remote/alarms/.venv/bin/swf-alarms-run \
     --config /home/admin/github/swf-remote/alarms/config.toml --dry-run -v
   ```

   (Drop `--dry-run` to send real emails.)

5. **Django side picks up the PARAMS help immediately.** The editor
   imports the alarm module to render its PARAMS help panel, so as
   soon as the dev tree is deployed via `deploy/update_from_dev.sh`,
   the editor shows the new alarm's param surface.

Removing an alarm: set `enabled=False` (keeps history visible), or
`archived=True` (hides from dashboard). The module file can stay — it's
harmless code until referenced by an Entry.

## Adding a new channel

Add `send_<channel>(alarm, **cfg) -> bool` in `alarms/swf_alarms/notify.py`.
Wire it into `run.py` behind a per-alarm or global `channels` config knob.
Failures must return False (never raise) so one stuck channel doesn't
cascade.

## Files (where the code lives)

**Django side** (`src/remote_app/`):

| File | Purpose |
|---|---|
| `models.py` | `EntryContext`, `Entry`, `EntryVersion`. tjai-faithful fields; `archived` boolean; pinned `db_table` names. |
| `migrations/0001_initial.py` | Schema. |
| `migrations/0002_seed_alarms.py` | Seeds `swf-alarms` context + initial alarm configs. |
| `migrations/0003_seed_teams.py` | Seeds the `teams` context + `@prodops`; adds `renotification_window_hours` to existing alarms. |
| `migrations/0005_drop_alarm_kind.py` | Drops legacy `data.kind` from alarm rows (pre-snowflake residue). |
| `migrations/0006_rename_days_window.py` | Renames `data.params.days_window` → `since_days` on existing alarm rows. |
| `signals.py` | `pre_save` snapshot on Entry. |
| `alarms_data.py` | ORM query helpers. Functions named `events_since`, `count_events_since`, `quiet_alarms`. |
| `alarm_views.py` | `alarms_dashboard`, `alarm_event_detail`, `alarm_config_edit/save/version`, `alarm_test`, `alarm_preview`, team views. Reads alarm modules' `PARAMS` for the editor help panel. |
| `views.py` | Re-exports alarm views. |
| `urls.py` | Alarm routes. |
| `templates/monitor_app/alarms.html` | Dashboard. |
| `templates/monitor_app/alarm_config_edit.html` | Editor. |
| `templates/monitor_app/alarm_event_detail.html` | Single firing detail. |
| `templates/monitor_app/team_edit.html` | Team editor. |
| `templatetags/swf_fmt.py` | `fmt_dt` and `state_class`. |
| `monitor_client.py` | Alarms-link injection in proxied HTML. |
| `src/templates/base.html` | Prod-style header nav + Alarms link. |

**Engine side** (`alarms/`):

| File | Purpose |
|---|---|
| `swf_alarms/config.py` | TOML loader — engine-level settings + DB DSN. |
| `swf_alarms/db.py` | psycopg layer over `entry`/`entry_context`/`entry_version`. Helpers: `list_alarm_configs`, `active_events_for_alarm`, `create_event`, `touch_event_last_seen`, `clear_event`, `start/finish_engine_run`. |
| `swf_alarms/fetch.py` | HTTP client for the swf-monitor REST. |
| `swf_alarms/lib/__init__.py` | `Detection` dataclass — the value-type alarm modules yield. |
| `swf_alarms/lib/failure_rate.py` | Shared PanDA-task failure-rate helper + its `PARAMS`. |
| `swf_alarms/alarms/<name>.py` | One snowflake alarm module per configured alarm. Currently: `panda_failure_rate_sakib`, `panda_failure_rate_eic_all`. |
| `swf_alarms/run.py` | Engine entry point. Loads configs, drives active/clear semantics, writes events + engine_run entries. Supports `--dry-run`. |
| `swf_alarms/notify.py` | SES send. Channel failures log but never raise. |
| `deploy/install.sh` | venv + log dir. Schema is owned by swf-remote migrations. |
| `deploy/crontab.example` | */5 min cadence. |
| `config.toml.example` | Engine, DB, email only. |
| `pyproject.toml` | `httpx`, `boto3`, `psycopg[binary]`. |

## Future work

- Mattermost channel (SES-parallel).
- Per-task-owner routing (lookup task username → recipient at
  event-create time; config recipients list becomes a fallback).
- Acknowledgement: ack button on active events to suppress notify
  without waiting for auto-clear.
- Time-bucket charts per alarm (events/hour over last N days).
