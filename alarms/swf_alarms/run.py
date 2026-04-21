"""swf-alarms engine entry point.

Per-tick behavior (active/clear semantics):

  1. Load kind='alarm' entries (not archived, enabled) from the DB.
  2. For each alarm config:
     a. Fetch existing active events for this alarm (one per entity still
        firing) — indexed by data.dedupe_key.
     b. Run the check; collect the dedupe_keys it yields this tick.
     c. For each detection:
          - If already active for same dedupe_key: touch last_seen, no email.
          - Else: create new event entry (fire_time=now, clear_time=null),
            compose email body (alarm.content + detection body_context),
            send email, log outcome.
     d. For each previously-active event NOT in the current detection set:
        set data.clear_time = now (auto-clear).
  3. Close out kind='engine_run' entry with aggregate counters + per-check
     detail.

No cooldown flag: dedup is *state-based* — one active event per (alarm,
entity). Re-firings only happen after a cleared→fire transition. This is
tjai-style state, which is what Torre asked for.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback

from . import config as config_mod
from . import db
from .checks import REGISTRY, Detection
from .fetch import Client, FetchError
from .notify import Alarm, send_email_ses


log = logging.getLogger("swf_alarms")


def _configure_logging(log_path: str | None, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_path:
        handlers.append(logging.FileHandler(log_path))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers, force=True,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="swf-alarms-run")
    ap.add_argument("--config", required=True, help="path to engine TOML")
    ap.add_argument("--dry-run", action="store_true",
                    help="detect and persist, but suppress notifications")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    cfg = config_mod.load(args.config)
    _configure_logging(cfg.engine.log_path, args.verbose)

    log.info("run starting  config=%s  dry_run=%s", args.config, args.dry_run)
    conn = db.connect(cfg.db_dsn)
    run_uuid = db.start_engine_run(conn)

    client = Client(cfg.engine.swf_remote_base_url,
                    timeout=cfg.engine.request_timeout)

    alarm_configs = db.list_alarm_configs(conn, enabled_only=True)
    log.info("loaded %d enabled alarm config(s)", len(alarm_configs))

    checks_run = 0
    alarms_seen = 0
    notifications_sent = 0
    errors = 0
    error_traces: list[str] = []
    per_check: dict[str, dict] = {}

    for alarm in alarm_configs:
        data = alarm.get("data") or {}
        alarm_entry_id = data.get("entry_id", "")
        kind = data.get("kind")
        if not alarm_entry_id or not kind:
            log.error("alarm %s missing data.entry_id or data.kind — skipping",
                      alarm["id"])
            errors += 1
            continue
        if kind not in REGISTRY:
            msg = f"unknown alarm kind {kind!r}"
            log.error("%s (entry_id=%s) — skipping", msg, alarm_entry_id)
            errors += 1
            error_traces.append(f"[{alarm_entry_id}] {msg}")
            per_check[alarm_entry_id] = {
                "kind": kind, "enabled": True,
                "alarms_seen": 0, "errors": 1, "error_message": msg,
            }
            continue

        checks_run += 1
        fn = REGISTRY[kind]
        params = dict(data.get("params") or {})
        severity = data.get("severity", "warning")
        raw_recipients = list(data.get("recipients") or [])
        # Resolve @<team> tokens to member emails via DB lookup.
        recipients, unresolved_teams = db.resolve_recipients(conn, raw_recipients)
        if unresolved_teams:
            log.warning("alarm %s: unresolved team(s) %s — skipped",
                        alarm_entry_id, unresolved_teams)
        # Per-alarm renotification window (hours). 0 / missing = no
        # re-notification — a still-firing entity stays quiet until clear.
        renotification_window_hours = float(
            data.get("renotification_window_hours") or 0)

        check_seen = 0
        check_err = 0
        check_err_msg = ""
        detected_keys: set[str] = set()

        # Existing active events for this alarm — map dedupe_key → row
        try:
            active_rows = db.active_events_for_alarm(conn, alarm_entry_id)
        except Exception as e:  # noqa: BLE001
            log.error("active_events_for_alarm(%s) failed: %s",
                      alarm_entry_id, e)
            active_rows = []
        active_by_key = {
            (r.get("data") or {}).get("dedupe_key"): r for r in active_rows
        }

        try:
            for det in fn(client, params):  # type: Detection
                check_seen += 1
                alarms_seen += 1
                detected_keys.add(det.dedupe_key)
                existing = active_by_key.get(det.dedupe_key)
                full_body = _compose_body(alarm.get("content") or "",
                                          det.body_context)

                if existing is None:
                    # NEW entity crosses threshold → create event + email.
                    event_uuid = db.create_event(
                        conn,
                        alarm_entry_id=alarm_entry_id,
                        dedupe_key=det.dedupe_key,
                        severity=severity,
                        subject=det.subject,
                        body=full_body,
                        recipients=recipients,
                        extra_data=det.extra_data,
                        alarm_config_uuid=alarm["id"],
                    )
                    if _try_send(args.dry_run, recipients, severity,
                                 alarm_entry_id, det, full_body, cfg):
                        db.mark_event_notified(conn, event_uuid)
                        notifications_sent += 1
                    continue

                # Same entity already firing — always bump last_seen.
                db.touch_event_last_seen(conn, existing["id"])

                # Re-notify only if a window is set and enough time has
                # elapsed since the last email.
                if renotification_window_hours <= 0:
                    continue
                last_notified = float(
                    (existing.get("data") or {}).get("last_notified") or 0)
                if (time.time() - last_notified) < renotification_window_hours * 3600:
                    continue

                if _try_send(args.dry_run, recipients, severity,
                             alarm_entry_id, det, full_body, cfg):
                    db.mark_event_notified(conn, existing["id"])
                    notifications_sent += 1
        except FetchError as e:
            log.error("alarm %s fetch failed: %s", alarm_entry_id, e)
            errors += 1
            check_err = 1
            check_err_msg = f"fetch: {e}"
            error_traces.append(f"[{alarm_entry_id}] fetch: {e}")
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            log.error("alarm %s raised:\n%s", alarm_entry_id, tb)
            errors += 1
            check_err = 1
            check_err_msg = tb
            error_traces.append(f"[{alarm_entry_id}]\n{tb}")

        # Auto-clear events whose dedupe_key wasn't seen this tick.
        # Only do so if the check ran without error — otherwise we'd clear
        # everything on a transient fetch failure.
        if check_err == 0:
            for key, ev in active_by_key.items():
                if key not in detected_keys:
                    try:
                        db.clear_event(conn, ev["id"])
                    except Exception as e:  # noqa: BLE001
                        log.error("clear_event failed for %s: %s", ev["id"], e)

        per_check[alarm_entry_id] = {
            "kind": kind,
            "enabled": True,
            "alarms_seen": check_seen,
            "errors": check_err,
            "error_message": check_err_msg,
            "params": params,
            "severity": severity,
            "recipients": recipients,
        }

    db.finish_engine_run(
        conn, run_uuid,
        checks_run=checks_run,
        alarms_seen=alarms_seen,
        notifications_sent=notifications_sent,
        errors=errors,
        error_details="\n\n".join(error_traces),
        per_check=per_check,
    )
    log.info("run done  checks=%d  alarms_seen=%d  sent=%d  errors=%d",
             checks_run, alarms_seen, notifications_sent, errors)
    return 0 if errors == 0 else 1


def _compose_body(alarm_description: str, detail: str) -> str:
    if alarm_description and alarm_description.strip():
        return f"{alarm_description.rstrip()}\n\n---\n\n{detail}"
    return detail


def _try_send(dry_run: bool, recipients, severity: str,
              alarm_entry_id: str, det, body: str, cfg) -> bool:
    """Send SES unless dry-run or no recipients. Returns True on success."""
    if dry_run or not recipients:
        return False
    from .checks import Detection  # noqa: F401 — helps mypy; import is free
    ok = send_email_ses(
        Alarm(
            check_name=alarm_entry_id,
            dedupe_key=det.dedupe_key,
            severity=severity,
            subject=det.subject,
            body=body,
            recipients=list(recipients),
            data=det.extra_data,
        ),
        region=cfg.email.region,
        from_addr=cfg.email.from_addr,
    )
    return ok


if __name__ == "__main__":
    sys.exit(main())
