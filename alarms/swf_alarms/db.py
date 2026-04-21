"""Postgres access to swf-remote's `entry` / `entry_context` tables.

The alarm engine runs standalone (no Django), but the state it writes lives
in swf-remote's own Postgres, not a side store. Schema is owned by Django
migrations in remote_app/models.py. Everything here is raw SQL against:

    entry             — generic document rows (kind='alarm' configs,
                        kind='event' firings, kind='engine_run' ticks, …)
    entry_context     — named project/topic groupings

Conventions used by the alarm system:
    context.name       = 'swf-alarms'
    kind='alarm'       — one per configured alarm, data.entry_id like
                         'alarm_panda_failure_rate_sakib'.
                         data = {kind, enabled, severity, recipients,
                                 params, ...}
                         content = human-readable description (used as
                         the top of alarm emails; editable in the UI).
    kind='event'       — one per firing instance. Shares
                         data.entry_id = 'event_<alarm_name>' with all
                         other firings of that alarm (non-unique).
                         data = {fire_time, clear_time (null=active),
                                 dedupe_key, subject, severity, recipients,
                                 alarm_config_id, ...context...}
                         content = body text used in the email.
    kind='engine_run'  — one per engine tick. data = summary counters.

Archive: status='archive' is filtered out of live dashboard queries.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


log = logging.getLogger(__name__)

CONTEXT_NAME = 'swf-alarms'


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_ts() -> float:
    return time.time()


def new_uuid() -> str:
    return str(uuid.uuid4())


def connect(dsn: str):
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def init_schema(conn) -> None:
    """No-op — migrations own the schema. Kept for API symmetry."""
    return


@contextmanager
def transaction(conn):
    with conn.transaction():
        yield


# ── alarm configs ──────────────────────────────────────────────────────────

def list_alarm_configs(conn, *, enabled_only: bool = True) -> list[dict]:
    """Load all non-archived alarm config entries from the swf-alarms context.

    Returns rows ordered by data.entry_id ascending for deterministic runs.
    """
    q = """
        SELECT e.*
        FROM entry e
        JOIN entry_context c ON c.name = e.context_id
        WHERE c.name = %s
          AND e.kind = 'alarm'
          AND e.archived = FALSE
          AND e.deleted_at IS NULL
        ORDER BY e.data->>'entry_id'
    """
    with conn.cursor() as cur:
        cur.execute(q, (CONTEXT_NAME,))
        rows = cur.fetchall()
    if enabled_only:
        rows = [r for r in rows if (r.get('data') or {}).get('enabled', True)]
    return rows


# ── events (firings) ───────────────────────────────────────────────────────

def active_events_for_alarm(conn, alarm_entry_id: str) -> list[dict]:
    """All currently-active (fire_time set, clear_time null) events for this
    alarm. Archived events are excluded."""
    q = """
        SELECT * FROM entry
        WHERE kind = 'event'
          AND context_id = %s
          AND data->>'entry_id' = %s
          AND (data->>'clear_time') IS NULL
          AND archived = FALSE
          AND deleted_at IS NULL
    """
    event_entry_id = f"event_{alarm_entry_id[len('alarm_'):]}" if alarm_entry_id.startswith('alarm_') else f"event_{alarm_entry_id}"
    with conn.cursor() as cur:
        cur.execute(q, (CONTEXT_NAME, event_entry_id))
        return cur.fetchall()


def create_event(conn, *, alarm_entry_id: str, dedupe_key: str,
                 severity: str, subject: str, body: str,
                 recipients: list[str], extra_data: dict,
                 alarm_config_uuid: str) -> str:
    """Insert a new kind='event' entry with fire_time=now, clear_time=null.

    Returns the new Entry UUID.
    """
    event_entry_id = f"event_{alarm_entry_id[len('alarm_'):]}" if alarm_entry_id.startswith('alarm_') else f"event_{alarm_entry_id}"
    now = now_ts()
    data = {
        'entry_id': event_entry_id,
        'fire_time': now,
        'clear_time': None,
        'last_seen': now,
        'dedupe_key': dedupe_key,
        'subject': subject,
        'severity': severity,
        'recipients': list(recipients),
        'alarm_config_id': alarm_config_uuid,
        **extra_data,
    }
    # last_notified is set now because create_event always accompanies an
    # initial notification attempt (or a dry-run skip). Engine re-notify
    # logic compares (now - last_notified) against the per-alarm window.
    data['last_notified'] = now
    new_id = new_uuid()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO entry
               (id, title, content, kind, context_id, data, status,
                archived, timestamp_created, timestamp_modified)
               VALUES (%s, %s, %s, 'event', %s, %s::jsonb, 'active',
                       FALSE, %s, %s)""",
            (new_id, subject[:255], body, CONTEXT_NAME,
             json.dumps(data, default=str), now, now),
        )
    return new_id


def touch_event_last_seen(conn, event_uuid: str) -> None:
    """Bump data.last_seen (and timestamp_modified) on an active event."""
    now = now_ts()
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE entry
               SET data = jsonb_set(data, '{last_seen}', to_jsonb(%s::float8), true),
                   timestamp_modified = %s
               WHERE id = %s""",
            (now, now, event_uuid),
        )


def mark_event_notified(conn, event_uuid: str) -> None:
    """Set data.last_notified = now on an event — bumped on every email."""
    now = now_ts()
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE entry
               SET data = jsonb_set(data, '{last_notified}', to_jsonb(%s::float8), true),
                   timestamp_modified = %s
               WHERE id = %s""",
            (now, now, event_uuid),
        )


def resolve_recipients(conn, tokens: list[str] | None) -> tuple[list[str], list[str]]:
    """Expand @<team> tokens into their member emails using the DB.

    Same contract as remote_app.alarms_data.expand_recipients(): returns
    (emails, unresolved). Tokens may be emails or @<team>; comma/whitespace
    separators already split by the caller.
    """
    if not tokens:
        return [], []
    emails: list[str] = []
    unresolved: list[str] = []
    for tok in tokens:
        t = (tok or '').strip()
        if not t:
            continue
        if t.startswith('@'):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content FROM entry WHERE context_id='teams' "
                    "AND kind='team' AND name=%s AND archived=FALSE "
                    "AND deleted_at IS NULL",
                    (t,),
                )
                row = cur.fetchone()
            if row is None or not (row.get('content') or '').strip():
                unresolved.append(t)
                continue
            for part in _split_tokens(row['content']):
                emails.append(part)
        else:
            emails.append(t)
    # Dedup case-insensitively on emails while preserving order.
    seen: set[str] = set()
    final: list[str] = []
    for e in emails:
        k = e.lower()
        if k in seen:
            continue
        seen.add(k)
        final.append(e)
    return final, unresolved


def _split_tokens(s: str) -> list[str]:
    for sep in [',', ';', '\n', '\r', '\t']:
        s = s.replace(sep, ' ')
    return [t.strip() for t in s.split(' ') if t.strip()]


def clear_event(conn, event_uuid: str) -> None:
    """Set data.clear_time = now on an event (condition has resolved)."""
    now = now_ts()
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE entry
               SET data = jsonb_set(data, '{clear_time}', to_jsonb(%s::float8), true),
                   timestamp_modified = %s
               WHERE id = %s""",
            (now, now, event_uuid),
        )


# ── engine runs ────────────────────────────────────────────────────────────

def start_engine_run(conn) -> str:
    """Create a kind='engine_run' entry with started_at; return its UUID."""
    now = now_ts()
    uid = new_uuid()
    title = f"Engine run {datetime.fromtimestamp(now, tz=timezone.utc).strftime('%Y%m%d %H:%M:%S UTC')}"
    data = {'entry_id': f'run_{int(now)}', 'started_at': now}
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO entry
               (id, title, content, kind, context_id, data, status,
                archived, timestamp_created, timestamp_modified)
               VALUES (%s, %s, '', 'engine_run', %s, %s::jsonb, 'active',
                       FALSE, %s, %s)""",
            (uid, title, CONTEXT_NAME, json.dumps(data), now, now),
        )
    return uid


def finish_engine_run(conn, run_uuid: str, *, checks_run: int,
                      alarms_seen: int, notifications_sent: int,
                      errors: int, error_details: str = '',
                      per_check: dict | None = None) -> None:
    now = now_ts()
    update = {
        'finished_at': now,
        'checks_run': checks_run,
        'alarms_seen': alarms_seen,
        'notifications_sent': notifications_sent,
        'errors': errors,
        'error_details': error_details,
        'per_check': per_check or {},
    }
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE entry
               SET data = data || %s::jsonb,
                   status = 'done',
                   timestamp_modified = %s
               WHERE id = %s""",
            (json.dumps(update, default=str), now, run_uuid),
        )
