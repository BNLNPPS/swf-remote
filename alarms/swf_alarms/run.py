"""Main entry point — run one pass of all enabled checks, notify, persist.

Design: deterministic, idempotent, crash-safe.
- Each run opens a transaction per alarm so a crash mid-run doesn't leave
  orphaned state.
- Cooldown governs notification, NOT detection. Detection runs every tick
  and `last_seen_at` is updated each time — so the dashboard reflects
  current truth. Email is the rate-limited channel.
- Notifications must never throw. A failed send is logged and accounted
  for in the run record.
- An alarm that wasn't seen this run is NOT auto-cleared. Cooldown keeps
  us quiet; explicit clearing is a future feature (likely user-driven
  via the dashboard, or time-based "not seen in N runs → clear").
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from datetime import datetime, timedelta, timezone

from . import config as config_mod
from . import db
from .checks import REGISTRY
from .fetch import Client, FetchError
from .notify import send_email_ses


log = logging.getLogger("swf_alarms")


def _cooldown_until(hours: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _is_in_cooldown(cooldown_until) -> bool:
    if cooldown_until is None:
        return False
    now = datetime.now(timezone.utc)
    if isinstance(cooldown_until, str):
        try:
            cooldown_until = datetime.fromisoformat(cooldown_until)
        except ValueError:
            return False
    if cooldown_until.tzinfo is None:
        cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
    return now < cooldown_until


def _configure_logging(log_path: str | None, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_path:
        handlers.append(logging.FileHandler(log_path))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="swf-alarms-run")
    ap.add_argument("--config", required=True, help="path to TOML config")
    ap.add_argument("--dry-run", action="store_true",
                    help="detect and persist, but suppress notifications")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    cfg = config_mod.load(args.config)
    _configure_logging(cfg.engine.log_path, args.verbose)

    log.info("run starting  config=%s  dry_run=%s", args.config, args.dry_run)
    conn = db.connect(cfg.db_dsn)

    run_id = db.start_run(conn)
    client = Client(cfg.engine.swf_remote_base_url, timeout=cfg.engine.request_timeout)

    checks_run = 0
    alarms_seen = 0
    notifications_sent = 0
    errors = 0
    error_traces: list[str] = []

    for check in cfg.checks:
        check_started = db.now_utc()
        params_snapshot = json.dumps({
            "severity": check.severity,
            "recipients": check.recipients,
            "cooldown_hours": check.cooldown_hours,
            "params": check.params,
        }, sort_keys=True, default=str)

        if not check.enabled:
            log.info("skip disabled check: %s", check.name)
            db.record_check_run(
                conn, run_id=run_id, check_name=check.name, kind=check.kind,
                enabled=False, started_at=check_started, alarms_seen=0,
                errors=0, params_snapshot_json=params_snapshot,
            )
            continue
        if check.kind not in REGISTRY:
            msg = f"unknown check kind {check.kind!r}"
            log.error("%s (name=%s) — skipping", msg, check.name)
            errors += 1
            error_traces.append(f"[{check.name}] {msg}")
            db.record_check_run(
                conn, run_id=run_id, check_name=check.name, kind=check.kind,
                enabled=True, started_at=check_started, alarms_seen=0,
                errors=1, error_message=msg,
                params_snapshot_json=params_snapshot,
            )
            continue

        log.info("running check: name=%s kind=%s", check.name, check.kind)
        checks_run += 1
        fn = REGISTRY[check.kind]

        params = dict(check.params)
        params["_recipients"] = check.recipients
        params["_severity"] = check.severity
        params["_check_name"] = check.name

        check_seen = 0
        check_err_message = ""
        check_err = 0
        try:
            for alarm in fn(client, params):
                check_seen += 1
                if _persist_and_maybe_notify(conn, check, alarm,
                                             cfg.email, dry_run=args.dry_run):
                    notifications_sent += 1
        except FetchError as e:
            log.error("check %s fetch failed: %s", check.name, e)
            errors += 1
            check_err = 1
            check_err_message = f"fetch: {e}"
            error_traces.append(f"[{check.name}] fetch: {e}")
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            log.error("check %s raised:\n%s", check.name, tb)
            errors += 1
            check_err = 1
            check_err_message = tb
            error_traces.append(f"[{check.name}]\n{tb}")
        alarms_seen += check_seen

        db.record_check_run(
            conn, run_id=run_id, check_name=check.name, kind=check.kind,
            enabled=True, started_at=check_started, alarms_seen=check_seen,
            errors=check_err, error_message=check_err_message,
            params_snapshot_json=params_snapshot,
        )

    db.finish_run(
        conn, run_id,
        checks_run=checks_run,
        alarms_seen=alarms_seen,
        notifications_sent=notifications_sent,
        errors=errors,
        error_details="\n\n".join(error_traces),
    )
    log.info(
        "run done  checks=%d  alarms_seen=%d  sent=%d  errors=%d",
        checks_run, alarms_seen, notifications_sent, errors,
    )
    return 0 if errors == 0 else 1


def _persist_and_maybe_notify(conn, check, alarm: Alarm, email_cfg,
                              *, dry_run: bool) -> bool:
    """Persist the alarm; notify if not in cooldown. Returns True if sent."""
    existing = db.get_firing(conn, alarm.check_name, alarm.dedupe_key)
    in_cooldown = existing is not None and _is_in_cooldown(existing["cooldown_until"])

    will_notify = not in_cooldown and not dry_run
    cooldown_until = _cooldown_until(check.cooldown_hours) if will_notify else (
        existing["cooldown_until"] if existing else None
    )

    firing_id, is_new, was_cleared = db.upsert_firing(
        conn,
        check_name=alarm.check_name,
        dedupe_key=alarm.dedupe_key,
        severity=alarm.severity,
        subject=alarm.subject,
        body=alarm.body,
        recipients=alarm.recipients,
        data=alarm.data,
        cooldown_until=cooldown_until,
    )
    if is_new:
        db.log_event(conn, firing_id, "fired", f"severity={alarm.severity}")
    elif was_cleared:
        db.log_event(conn, firing_id, "re-fired", "state: cleared -> active")
    else:
        db.log_event(conn, firing_id, "re-confirmed", "")

    if dry_run:
        db.log_event(conn, firing_id, "notify-skipped-dry-run", "")
        return False
    if in_cooldown:
        db.log_event(conn, firing_id, "notify-skipped-cooldown",
                     f"until={existing['cooldown_until']}")
        return False

    ok = send_email_ses(alarm, region=email_cfg.region, from_addr=email_cfg.from_addr)
    if ok:
        db.log_event(conn, firing_id, "notified",
                     f"channel=email recipients={','.join(alarm.recipients)}")
        return True
    db.log_event(conn, firing_id, "notify-failed",
                 f"channel=email recipients={','.join(alarm.recipients)}")
    return False


if __name__ == "__main__":
    sys.exit(main())
