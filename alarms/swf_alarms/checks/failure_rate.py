"""Task failure-rate check.

Fires when a task's computed_failurerate exceeds threshold. Uses
computed_failurerate (nfailed / (nfailed+nfinished)) rather than the native
JEDI failurerate column, which is usually NULL in this ePIC PanDA deployment
— see swf-monitor v35 commit 06bd974 for the details.

params (TOML):
  threshold          float, e.g. 0.03 for 3%
  days_window        int, tasks modified within this many days, default 1
  workinggroup       str, e.g. "EIC", optional
  username           str, optional — pattern supports % (LIKE)
  processingtype     str, optional
  min_terminal_jobs  int, ignore tasks with fewer terminal jobs (reduces
                     noise on tasks that have only a handful of job
                     attempts), default 5
  statuses           list[str], task.status values to consider; defaults to
                     ['running', 'failed', 'broken']. 'done' and 'finished'
                     are omitted by default because a completed task's
                     failure rate is a post-mortem, not an actionable signal.
"""
from __future__ import annotations

from ..notify import Alarm


DEFAULT_STATUSES = ["running", "failed", "broken"]


def task_failure_rate(client, params: dict):
    threshold = float(params["threshold"])
    days = int(params.get("days_window", 1))
    workinggroup = params.get("workinggroup")
    username = params.get("username")
    processingtype = params.get("processingtype")
    min_terminal = int(params.get("min_terminal_jobs", 5))
    statuses = params.get("statuses") or DEFAULT_STATUSES
    check_name = params.get("_check_name") or "task_failure_rate"

    for status in statuses:
        for t in client.iter_all_tasks(
            days=days, status=status,
            workinggroup=workinggroup,
            username=username,
            processingtype=processingtype,
        ):
            cfr = t.get("computed_failurerate")
            if cfr is None:
                continue
            nfailed = int(t.get("nfailed") or 0)
            nfinished = int(t.get("nfinished") or 0)
            if nfailed + nfinished < min_terminal:
                continue
            if cfr < threshold:
                continue

            jeditaskid = t["jeditaskid"]
            taskname = t.get("taskname") or "?"
            site = t.get("site") or "?"
            task_status = t.get("status") or "?"
            task_user = t.get("username") or "?"
            wg = t.get("workinggroup") or "?"
            rate_pct = cfr * 100.0

            subject = (
                f"[PanDA] task {jeditaskid} ({task_status}) "
                f"failure rate {rate_pct:.1f}% — {taskname}"
            )
            body = _format_body(
                check_name=check_name,
                jeditaskid=jeditaskid, taskname=taskname, task_status=task_status,
                task_user=task_user, wg=wg, site=site, cfr=cfr, nfailed=nfailed,
                nfinished=nfinished, nactive=int(t.get("nactive") or 0),
                threshold=threshold, days=days, native_failurerate=t.get("failurerate"),
            )
            yield Alarm(
                check_name=check_name,
                dedupe_key=f"task:{jeditaskid}",
                severity=params.get("_severity", "warning"),
                subject=subject,
                body=body,
                recipients=list(params.get("_recipients") or []),
                data={
                    "jeditaskid": jeditaskid,
                    "taskname": taskname,
                    "status": task_status,
                    "username": task_user,
                    "workinggroup": wg,
                    "site": site,
                    "computed_failurerate": cfr,
                    "native_failurerate": t.get("failurerate"),
                    "nactive": int(t.get("nactive") or 0),
                    "nfinished": nfinished,
                    "nfailed": nfailed,
                    "threshold": threshold,
                    "days_window": days,
                },
            )


def _format_body(**k) -> str:
    native = k["native_failurerate"]
    native_line = (
        f"JEDI native failurerate: {native} (computed is the operative signal)"
        if native is not None
        else "JEDI native failurerate: NULL (expected — not populated for ePIC task types)"
    )
    return (
        f"PanDA task {k['jeditaskid']} — {k['taskname']}\n"
        f"Status:      {k['task_status']}\n"
        f"Owner:       {k['task_user']}  (working group: {k['wg']})\n"
        f"Site:        {k['site']}\n"
        f"\n"
        f"Computed failure rate: {k['cfr']*100:.1f}%  (threshold {k['threshold']*100:.1f}%)\n"
        f"Jobs: nfailed={k['nfailed']}  nfinished={k['nfinished']}  nactive={k['nactive']}\n"
        f"Window: last {k['days']} day(s)\n"
        f"{native_line}\n"
        f"\n"
        f"Task page:  https://epic-devcloud.org/prod/panda/tasks/{k['jeditaskid']}/\n"
        f"Alarm dashboard: https://epic-devcloud.org/prod/alarms/"
        f"#{k['check_name']}:task:{k['jeditaskid']}\n"
    )
