"""Task failure-rate check.

Emits one Detection per PanDA task whose computed_failurerate exceeds the
configured threshold. Uses `computed_failurerate` (nfailed / (nfailed+
nfinished)) rather than the native JEDI `failurerate` column, which is
usually NULL in this ePIC PanDA deployment (swf-monitor commit 06bd974).

params (from alarm config entry's data.params):
  threshold          float, e.g. 0.03 for 3%
  days_window        int, default 1
  workinggroup       str, optional, e.g. "EIC"
  username           str, optional (supports % LIKE wildcard upstream)
  processingtype     str, optional
  min_terminal_jobs  int, default 5 — noise floor: tasks with fewer
                     terminal jobs are skipped
  statuses           list[str], task statuses to consider; defaults to
                     ['running','failed','broken']
"""
from __future__ import annotations


DEFAULT_STATUSES = ["running", "failed", "broken"]


def task_failure_rate(client, params: dict):
    from . import Detection  # avoid circular import at module load

    threshold = float(params["threshold"])
    days = int(params.get("days_window", 1))
    workinggroup = params.get("workinggroup")
    username = params.get("username")
    processingtype = params.get("processingtype")
    min_terminal = int(params.get("min_terminal_jobs", 5))
    statuses = params.get("statuses") or DEFAULT_STATUSES

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
            yield Detection(
                dedupe_key=f"task:{jeditaskid}",
                subject=(
                    f"[PanDA] task {jeditaskid} ({t.get('status') or '?'}) "
                    f"failure rate {cfr*100:.1f}% — {t.get('taskname') or '?'}"
                ),
                body_context=_body_detail(
                    jeditaskid=jeditaskid,
                    taskname=t.get("taskname") or "?",
                    task_status=t.get("status") or "?",
                    task_user=t.get("username") or "?",
                    wg=t.get("workinggroup") or "?",
                    site=t.get("site") or "?",
                    cfr=cfr, nfailed=nfailed, nfinished=nfinished,
                    nactive=int(t.get("nactive") or 0),
                    threshold=threshold, days=days,
                    native_failurerate=t.get("failurerate"),
                ),
                extra_data={
                    "jeditaskid": jeditaskid,
                    "taskname": t.get("taskname"),
                    "status": t.get("status"),
                    "username": t.get("username"),
                    "workinggroup": t.get("workinggroup"),
                    "site": t.get("site"),
                    "computed_failurerate": cfr,
                    "native_failurerate": t.get("failurerate"),
                    "nactive": int(t.get("nactive") or 0),
                    "nfinished": nfinished,
                    "nfailed": nfailed,
                    "threshold": threshold,
                    "days_window": days,
                },
            )


def _body_detail(**k) -> str:
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
        f"Task page: https://epic-devcloud.org/prod/panda/tasks/{k['jeditaskid']}/\n"
    )
