"""Query helpers for the alarm dashboard — Django ORM over the same
Postgres tables the standalone engine writes. No schema here; see
`models.py`.

Returns plain dicts (not model instances) so the templates keep the same
attribute style they had when they were backed by sqlite row dicts, and
so the health-banner helper can operate on a pickled snapshot without
hitting the DB again.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from django.db.models import Count, Max

from .models import AlarmCheckRun, AlarmFiring, AlarmFiringEvent, AlarmRun


def _firing_to_dict(f: AlarmFiring) -> dict:
    return {
        "id": f.id,
        "check_name": f.check_name,
        "dedupe_key": f.dedupe_key,
        "first_fired_at": f.first_fired_at,
        "last_fired_at": f.last_fired_at,
        "last_seen_at": f.last_seen_at,
        "cooldown_until": f.cooldown_until,
        "state": f.state,
        "cleared_at": f.cleared_at,
        "severity": f.severity,
        "subject": f.subject,
        "body": f.body,
        "recipients": f.recipients,
        "recipients_list": [r for r in f.recipients.split(",") if r],
        "data": f.data,
    }


def list_firings(state: str | None = None, limit: int = 200) -> list[dict]:
    qs = AlarmFiring.objects.all()
    if state:
        qs = qs.filter(state=state)
    return [_firing_to_dict(f) for f in qs.order_by("-last_fired_at")[:limit]]


def get_firing(firing_id: int) -> dict | None:
    try:
        f = AlarmFiring.objects.get(id=firing_id)
    except AlarmFiring.DoesNotExist:
        return None
    return _firing_to_dict(f)


def events_for(firing_id: int, limit: int = 200) -> list[dict]:
    qs = AlarmFiringEvent.objects.filter(firing_id=firing_id).order_by("-ts")[:limit]
    return [{"ts": e.ts, "action": e.action, "notes": e.notes} for e in qs]


def recent_runs(limit: int = 50) -> list[dict]:
    qs = AlarmRun.objects.order_by("-started_at")[:limit]
    return [{
        "id": r.id,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "checks_run": r.checks_run,
        "alarms_seen": r.alarms_seen,
        "notifications_sent": r.notifications_sent,
        "errors": r.errors,
    } for r in qs]


def summary() -> dict:
    """Counts + severity breakdown + engine health."""
    try:
        active = AlarmFiring.objects.filter(state="active").count()
        total = AlarmFiring.objects.count()
        sev_rows = (AlarmFiring.objects
                    .filter(state="active")
                    .values("severity")
                    .annotate(n=Count("id")))
        severity_counts = {r["severity"]: r["n"] for r in sev_rows}
        last_run = AlarmRun.objects.order_by("-started_at").first()
    except Exception:  # noqa: BLE001 — DB unreachable, degrade to empty
        return {"active": 0, "total": 0, "last_run": None,
                "severity_counts": {}, "available": False}

    return {
        "active": active,
        "total": total,
        "severity_counts": severity_counts,
        "last_run": {
            "started_at": last_run.started_at,
            "finished_at": last_run.finished_at,
            "checks_run": last_run.checks_run,
            "alarms_seen": last_run.alarms_seen,
            "notifications_sent": last_run.notifications_sent,
            "errors": last_run.errors,
        } if last_run else None,
        "available": True,
    }


def check_summary() -> list[dict]:
    """Per-check status — one row per configured check.

    Derived from the most recent AlarmCheckRun per check_name, plus a count
    of currently-active firings attributed to that check.
    """
    # Find the latest started_at per check_name
    latest_ts = (AlarmCheckRun.objects
                 .values("check_name")
                 .annotate(mx=Max("started_at")))
    latest_map = {r["check_name"]: r["mx"] for r in latest_ts}
    if not latest_map:
        return []

    # Pull the actual rows for those (check_name, mx) pairs.
    latest_rows = list(
        AlarmCheckRun.objects
        .filter(check_name__in=latest_map.keys())
        .order_by("check_name", "-started_at")
    )
    seen: set[str] = set()
    latest_per_check: list[AlarmCheckRun] = []
    for r in latest_rows:
        if r.check_name in seen:
            continue
        if r.started_at == latest_map[r.check_name]:
            latest_per_check.append(r)
            seen.add(r.check_name)

    # Active firing counts per check in one query.
    active_counts = {
        r["check_name"]: r["n"]
        for r in (AlarmFiring.objects
                  .filter(state="active")
                  .values("check_name")
                  .annotate(n=Count("id")))
    }
    # Last-fired timestamp per check.
    last_fired = {
        r["check_name"]: r["mx"]
        for r in (AlarmFiring.objects
                  .values("check_name")
                  .annotate(mx=Max("last_fired_at")))
    }

    out = []
    for r in sorted(latest_per_check, key=lambda x: x.check_name):
        out.append({
            "check_name": r.check_name,
            "kind": r.kind,
            "enabled": r.enabled,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "alarms_seen": r.alarms_seen,
            "errors": r.errors,
            "error_message": r.error_message,
            "params_snapshot": r.params_snapshot,
            "active_firings": active_counts.get(r.check_name, 0),
            "last_fired_at": last_fired.get(r.check_name),
        })
    return out


def overall_health(summary_dict: dict, checks: list[dict]) -> dict:
    """Compute a single traffic-light for the top banner.

    Returns {status, reasons[]} where status ∈ {'ok','warn','bad','unknown'}.
    """
    reasons: list[str] = []
    status = "ok"

    if not summary_dict.get("available"):
        return {"status": "unknown",
                "reasons": ["Alarm DB not reachable."]}

    last_run = summary_dict.get("last_run")
    if not last_run:
        return {"status": "unknown",
                "reasons": ["Engine has never run."]}

    finished = last_run.get("finished_at")
    if not finished:
        reasons.append("Last engine run did not finish (in progress or crashed).")
        status = "warn"
    else:
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - finished
        if age > timedelta(minutes=15):
            reasons.append(
                f"Engine stale: last run finished {int(age.total_seconds()//60)} min ago "
                f"(expected every 5 min)."
            )
            status = "bad"

    if last_run.get("errors"):
        reasons.append(f"Last run had {last_run['errors']} error(s).")
        status = "bad"

    sev = summary_dict.get("severity_counts") or {}
    if sev.get("critical"):
        reasons.append(f"{sev['critical']} critical alarm(s) active.")
        status = "bad"
    if sev.get("warning"):
        reasons.append(f"{sev['warning']} warning alarm(s) active.")
        if status == "ok":
            status = "warn"
    if sev.get("info"):
        reasons.append(f"{sev['info']} info alarm(s) active.")

    for c in checks:
        if c.get("errors"):
            reasons.append(f"Check {c['check_name']}: last run errored.")
            status = "bad"

    if status == "ok" and not reasons:
        reasons.append("All checks healthy, no active alarms.")
    return {"status": status, "reasons": reasons}
