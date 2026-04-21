"""Read-only sqlite reader for the swf-alarms state DB.

The alarm engine (swf-remote/alarms/) writes; Django just reads. No ORM,
no models, no migrations — keeps engine/dashboard decoupled. Path comes
from settings.SWF_ALARMS_DB; if the file doesn't exist yet (engine hasn't
run), views degrade to an empty result.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from django.conf import settings


@contextmanager
def _connect():
    path = getattr(settings, "SWF_ALARMS_DB", None)
    if not path:
        yield None
        return
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        yield None
        return
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _row_to_dict(row) -> dict:
    d = dict(row)
    if d.get("data_json"):
        try:
            d["data"] = json.loads(d["data_json"])
        except (ValueError, TypeError):
            d["data"] = None
    else:
        d["data"] = None
    if d.get("recipients"):
        d["recipients_list"] = [r for r in d["recipients"].split(",") if r]
    else:
        d["recipients_list"] = []
    return d


def list_firings(state: str | None = None, limit: int = 200) -> list[dict]:
    with _connect() as conn:
        if conn is None:
            return []
        try:
            if state:
                rows = conn.execute(
                    "SELECT * FROM firings WHERE state=? ORDER BY last_fired_at DESC LIMIT ?",
                    (state, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM firings ORDER BY last_fired_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.DatabaseError:
            return []
        return [_row_to_dict(r) for r in rows]


def get_firing(firing_id: int) -> dict | None:
    with _connect() as conn:
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT * FROM firings WHERE id=?", (firing_id,)
            ).fetchone()
        except sqlite3.DatabaseError:
            return None
        return _row_to_dict(row) if row else None


def get_firing_by_dedupe(check_name: str, dedupe_key: str) -> dict | None:
    with _connect() as conn:
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT * FROM firings WHERE check_name=? AND dedupe_key=?",
                (check_name, dedupe_key),
            ).fetchone()
        except sqlite3.DatabaseError:
            return None
        return _row_to_dict(row) if row else None


def events_for(firing_id: int, limit: int = 200) -> list[dict]:
    with _connect() as conn:
        if conn is None:
            return []
        try:
            rows = conn.execute(
                "SELECT * FROM events WHERE firing_id=? ORDER BY ts DESC LIMIT ?",
                (firing_id, limit),
            ).fetchall()
        except sqlite3.DatabaseError:
            return []
        return [dict(r) for r in rows]


def recent_runs(limit: int = 50) -> list[dict]:
    with _connect() as conn:
        if conn is None:
            return []
        try:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        except sqlite3.DatabaseError:
            return []
        return [dict(r) for r in rows]


def summary() -> dict:
    """Counts + severity breakdown + engine health for dashboard header."""
    with _connect() as conn:
        if conn is None:
            return {"active": 0, "total": 0, "last_run": None,
                    "severity_counts": {}, "available": False}
        try:
            active = conn.execute(
                "SELECT COUNT(*) FROM firings WHERE state='active'"
            ).fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM firings").fetchone()[0]
            rows = conn.execute(
                "SELECT severity, COUNT(*) AS n FROM firings "
                "WHERE state='active' GROUP BY severity"
            ).fetchall()
            severity_counts = {r["severity"]: r["n"] for r in rows}
            last = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        except sqlite3.DatabaseError:
            return {"active": 0, "total": 0, "last_run": None,
                    "severity_counts": {}, "available": False}
        return {
            "active": active,
            "total": total,
            "severity_counts": severity_counts,
            "last_run": dict(last) if last else None,
            "available": True,
        }


def check_summary() -> list[dict]:
    """Per-check status for the dashboard — one row per configured check.

    Derived from the most recent check_runs row per name, plus a count of
    currently-active firings attributed to that check.
    """
    with _connect() as conn:
        if conn is None:
            return []
        try:
            latest = conn.execute("""
                SELECT cr.*
                FROM check_runs cr
                JOIN (
                    SELECT check_name, MAX(started_at) AS mx
                    FROM check_runs
                    GROUP BY check_name
                ) t ON t.check_name = cr.check_name AND t.mx = cr.started_at
                ORDER BY cr.check_name
            """).fetchall()
        except sqlite3.DatabaseError:
            return []

        out = []
        for r in latest:
            try:
                active = conn.execute(
                    "SELECT COUNT(*) FROM firings WHERE check_name=? AND state='active'",
                    (r["check_name"],),
                ).fetchone()[0]
                last_fired_row = conn.execute(
                    "SELECT MAX(last_fired_at) AS last_fired FROM firings WHERE check_name=?",
                    (r["check_name"],),
                ).fetchone()
                last_fired = last_fired_row["last_fired"] if last_fired_row else None
            except sqlite3.DatabaseError:
                active, last_fired = 0, None
            d = dict(r)
            d["enabled"] = bool(d.get("enabled"))
            d["active_firings"] = active
            d["last_fired_at"] = last_fired
            if d.get("params_snapshot_json"):
                try:
                    d["params_snapshot"] = json.loads(d["params_snapshot_json"])
                except (ValueError, TypeError):
                    d["params_snapshot"] = None
            else:
                d["params_snapshot"] = None
            out.append(d)
        return out


def overall_health(summary_dict: dict, checks: list[dict]) -> dict:
    """Compute a single traffic-light for the top banner.

    Returns {status, reasons[]} where status ∈ {'ok','warn','bad','unknown'}.
    """
    from datetime import datetime, timezone, timedelta
    reasons: list[str] = []
    status = "ok"

    if not summary_dict.get("available"):
        return {"status": "unknown",
                "reasons": ["Alarm state DB not readable."]}

    last_run = summary_dict.get("last_run")
    if not last_run:
        return {"status": "unknown",
                "reasons": ["Engine has never run."]}

    finished = last_run.get("finished_at")
    if not finished:
        reasons.append("Last engine run did not finish (in progress or crashed).")
        status = "warn"
    else:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(finished)
            if age > timedelta(minutes=15):
                reasons.append(
                    f"Engine stale: last run finished {int(age.total_seconds()//60)} min ago "
                    f"(expected every 5 min)."
                )
                status = "bad"
        except ValueError:
            pass

    if last_run.get("errors"):
        reasons.append(f"Last run had {last_run['errors']} error(s).")
        status = "bad" if status != "bad" else status

    sev = summary_dict.get("severity_counts") or {}
    if sev.get("critical"):
        reasons.append(f"{sev['critical']} critical alarm(s) active.")
        status = "bad"
    if sev.get("warning"):
        reasons.append(f"{sev['warning']} warning alarm(s) active.")
        if status == "ok":
            status = "warn"
    if sev.get("info"):
        reasons.append(f"{sev.get('info', 0)} info alarm(s) active.")

    for c in checks:
        if c.get("errors"):
            reasons.append(f"Check {c['check_name']}: last run errored.")
            status = "bad"

    if status == "ok" and not reasons:
        reasons.append("All checks healthy, no active alarms.")
    return {"status": status, "reasons": reasons}
