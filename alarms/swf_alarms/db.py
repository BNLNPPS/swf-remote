"""sqlite state store for swf-alarms.

Schema:
  firings — one row per (check_name, dedupe_key). Holds current state
            (active/cleared), first/last-fired timestamps, cooldown,
            severity, subject, body, recipients, JSON context data.
  events  — append-only log of every state transition on a firing
            (fired, re-confirmed, notified, notify-skipped, cleared).
  runs    — one row per engine run; summary counters + error trace.

Access pattern: standalone engine writes; dashboard (Django view) reads.
No Django ORM — plain sqlite3 for minimal coupling.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS firings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_name TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    first_fired_at TEXT NOT NULL,
    last_fired_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    cooldown_until TEXT,
    state TEXT NOT NULL DEFAULT 'active',
    cleared_at TEXT,
    severity TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    recipients TEXT NOT NULL,
    data_json TEXT,
    UNIQUE(check_name, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_firings_state ON firings(state, last_fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_firings_check ON firings(check_name, last_fired_at DESC);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firing_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY(firing_id) REFERENCES firings(id)
);

CREATE INDEX IF NOT EXISTS idx_events_firing ON events(firing_id, ts DESC);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    checks_run INTEGER DEFAULT 0,
    alarms_seen INTEGER DEFAULT 0,
    notifications_sent INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    error_details TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);

CREATE TABLE IF NOT EXISTS check_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    check_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    alarms_seen INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    error_message TEXT,
    params_snapshot_json TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_check_runs_name ON check_runs(check_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_check_runs_run ON check_runs(run_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN")
    try:
        yield
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def get_firing(conn, check_name: str, dedupe_key: str):
    return conn.execute(
        "SELECT * FROM firings WHERE check_name=? AND dedupe_key=?",
        (check_name, dedupe_key),
    ).fetchone()


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
    cooldown_until: str | None,
) -> tuple[int, bool, bool]:
    """Insert or update a firing.

    Returns (firing_id, is_new, was_cleared) where:
      is_new      — first time we've seen this dedupe_key
      was_cleared — previous state was 'cleared'; we're re-opening it
    """
    ts = now_iso()
    existing = get_firing(conn, check_name, dedupe_key)
    recipients_csv = ",".join(recipients)
    data_json = json.dumps(data, default=str, sort_keys=True)

    if existing is None:
        cur = conn.execute(
            """INSERT INTO firings
               (check_name, dedupe_key, first_fired_at, last_fired_at,
                last_seen_at, cooldown_until, state, severity, subject,
                body, recipients, data_json)
               VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
            (check_name, dedupe_key, ts, ts, ts, cooldown_until,
             severity, subject, body, recipients_csv, data_json),
        )
        return cur.lastrowid, True, False

    was_cleared = existing["state"] == "cleared"
    conn.execute(
        """UPDATE firings SET
           last_fired_at=?, last_seen_at=?, cooldown_until=?,
           state='active', cleared_at=NULL,
           severity=?, subject=?, body=?, recipients=?, data_json=?
           WHERE id=?""",
        (ts, ts, cooldown_until, severity, subject, body,
         recipients_csv, data_json, existing["id"]),
    )
    return existing["id"], False, was_cleared


def clear_firing(conn, firing_id: int, note: str = "") -> None:
    ts = now_iso()
    conn.execute(
        "UPDATE firings SET state='cleared', cleared_at=? WHERE id=?",
        (ts, firing_id),
    )
    log_event(conn, firing_id, "cleared", note)


def log_event(conn, firing_id: int, action: str, notes: str = "") -> None:
    conn.execute(
        "INSERT INTO events (firing_id, ts, action, notes) VALUES (?, ?, ?, ?)",
        (firing_id, now_iso(), action, notes),
    )


def start_run(conn) -> int:
    cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (now_iso(),))
    return cur.lastrowid


def finish_run(conn, run_id: int, *, checks_run: int, alarms_seen: int,
               notifications_sent: int, errors: int, error_details: str = "") -> None:
    conn.execute(
        """UPDATE runs SET finished_at=?, checks_run=?, alarms_seen=?,
           notifications_sent=?, errors=?, error_details=? WHERE id=?""",
        (now_iso(), checks_run, alarms_seen, notifications_sent,
         errors, error_details or None, run_id),
    )


def record_check_run(conn, *, run_id: int, check_name: str, kind: str,
                     enabled: bool, started_at: str, alarms_seen: int,
                     errors: int, error_message: str = "",
                     params_snapshot_json: str | None = None) -> int:
    """Record a single check execution inside a run."""
    cur = conn.execute(
        """INSERT INTO check_runs
           (run_id, check_name, kind, enabled, started_at, finished_at,
            alarms_seen, errors, error_message, params_snapshot_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, check_name, kind, 1 if enabled else 0, started_at,
         now_iso(), alarms_seen, errors, error_message or None,
         params_snapshot_json),
    )
    return cur.lastrowid


def active_firings(conn):
    return conn.execute(
        "SELECT * FROM firings WHERE state='active' ORDER BY last_fired_at DESC"
    ).fetchall()


def firing_by_id(conn, firing_id: int):
    return conn.execute("SELECT * FROM firings WHERE id=?", (firing_id,)).fetchone()


def events_for_firing(conn, firing_id: int, limit: int = 200):
    return conn.execute(
        "SELECT * FROM events WHERE firing_id=? ORDER BY ts DESC LIMIT ?",
        (firing_id, limit),
    ).fetchall()


def recent_runs(conn, limit: int = 50):
    return conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()


def cli_init():
    """Console entry point: swf-alarms-initdb <db-path>"""
    if len(sys.argv) != 2:
        print("usage: swf-alarms-initdb <db-path>", file=sys.stderr)
        sys.exit(2)
    conn = connect(sys.argv[1])
    init_schema(conn)
    print(f"initialized {sys.argv[1]}")
