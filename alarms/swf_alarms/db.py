"""Postgres state store for swf-alarms.

The swf-remote Django app already owns a Postgres database; the alarm
engine writes to it directly via psycopg, and the Django dashboard reads
the same rows through its ORM. Schema is owned by swf-remote's migrations
(see remote_app/models.py). Table names are pinned there via `db_table` so
the SQL below can reference them without guessing app-prefixed names:

    alarm_run            AlarmRun
    alarm_check_run      AlarmCheckRun
    alarm_firing         AlarmFiring
    alarm_firing_event   AlarmFiringEvent

The engine remains standalone — no Django import, no settings bootstrap.
It just needs a DSN reachable from wherever it runs. Credentials can live
either in the engine's own config.toml or (by default) be read from
swf-remote's existing .env so there's one source of truth.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


log = logging.getLogger(__name__)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def connect(dsn: str):
    """Return a new autocommit connection with dict row factory."""
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def init_schema(conn) -> None:
    """No-op. Migrations own the schema (swf-remote/src/remote_app/migrations/).

    Retained so the runner's existing init_schema() call still works.
    """
    return


@contextmanager
def transaction(conn):
    with conn.transaction():
        yield


# ── firings ────────────────────────────────────────────────────────────────

def get_firing(conn, check_name: str, dedupe_key: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM alarm_firing WHERE check_name=%s AND dedupe_key=%s",
            (check_name, dedupe_key),
        )
        return cur.fetchone()


def upsert_firing(
    conn,
    *,
    check_name: str,
    dedupe_key: str,
    severity: str,
    subject: str,
    body: str,
    recipients: list[str],
    data: dict,
    cooldown_until: datetime | None,
) -> tuple[int, bool, bool]:
    """Insert-or-update a firing keyed on (check_name, dedupe_key).

    Returns (firing_id, is_new, was_cleared):
      is_new       — first time we've seen this dedupe_key
      was_cleared  — previous state was 'cleared'; re-opening it
    """
    existing = get_firing(conn, check_name, dedupe_key)
    now = now_utc()
    recipients_csv = ",".join(recipients)
    data_json = json.dumps(data, default=str, sort_keys=True)

    with conn.cursor() as cur:
        if existing is None:
            cur.execute(
                """INSERT INTO alarm_firing
                   (check_name, dedupe_key, first_fired_at, last_fired_at,
                    last_seen_at, cooldown_until, state, severity, subject,
                    body, recipients, data)
                   VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, %s, %s, %s, %s::jsonb)
                   RETURNING id""",
                (check_name, dedupe_key, now, now, now, cooldown_until,
                 severity, subject, body, recipients_csv, data_json),
            )
            return cur.fetchone()["id"], True, False

        was_cleared = existing["state"] == "cleared"
        cur.execute(
            """UPDATE alarm_firing SET
               last_fired_at=%s, last_seen_at=%s, cooldown_until=%s,
               state='active', cleared_at=NULL,
               severity=%s, subject=%s, body=%s, recipients=%s, data=%s::jsonb
               WHERE id=%s""",
            (now, now, cooldown_until, severity, subject, body,
             recipients_csv, data_json, existing["id"]),
        )
    return existing["id"], False, was_cleared


def clear_firing(conn, firing_id: int, note: str = "") -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE alarm_firing SET state='cleared', cleared_at=%s WHERE id=%s",
            (now_utc(), firing_id),
        )
    log_event(conn, firing_id, "cleared", note)


# ── events ─────────────────────────────────────────────────────────────────

def log_event(conn, firing_id: int, action: str, notes: str = "") -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO alarm_firing_event (firing_id, ts, action, notes) "
            "VALUES (%s, %s, %s, %s)",
            (firing_id, now_utc(), action, notes),
        )


# ── runs ───────────────────────────────────────────────────────────────────

def start_run(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO alarm_run (started_at) VALUES (%s) RETURNING id",
            (now_utc(),),
        )
        return cur.fetchone()["id"]


def finish_run(conn, run_id: int, *, checks_run: int, alarms_seen: int,
               notifications_sent: int, errors: int,
               error_details: str = "") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE alarm_run SET finished_at=%s, checks_run=%s,
               alarms_seen=%s, notifications_sent=%s, errors=%s,
               error_details=%s WHERE id=%s""",
            (now_utc(), checks_run, alarms_seen, notifications_sent,
             errors, error_details or '', run_id),
        )


def record_check_run(conn, *, run_id: int, check_name: str, kind: str,
                     enabled: bool, started_at: datetime, alarms_seen: int,
                     errors: int, error_message: str = "",
                     params_snapshot_json: str | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO alarm_check_run
               (run_id, check_name, kind, enabled, started_at, finished_at,
                alarms_seen, errors, error_message, params_snapshot)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
               RETURNING id""",
            (run_id, check_name, kind, enabled, started_at, now_utc(),
             alarms_seen, errors, error_message or '',
             params_snapshot_json),
        )
        return cur.fetchone()["id"]
