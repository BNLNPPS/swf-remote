"""Shared task-failure-rate helper.

Yields one Detection per PanDA task whose computed_failurerate exceeds the
configured threshold. Uses `computed_failurerate` (nfailed / (nfailed +
nfinished)) rather than the native JEDI `failurerate` column, which is
usually NULL in this ePIC PanDA deployment.

Alarm modules import and delegate to `task_failure_rate(client, params)`.
No central registry.

Params (read from the alarm config entry's data.params):

  threshold          float, required. e.g. 0.03 for 3%.
  since_days         int, default 1. How far back to look at PanDA data.
  username           str, optional (supports % LIKE wildcard upstream).
  processingtype     str, optional.
  min_terminal_jobs  int, default 5. Noise floor: tasks with fewer
                     terminal jobs are skipped.
  statuses           list[str], optional. Task statuses to consider;
                     defaults to ['running', 'failed', 'broken'].
"""
from __future__ import annotations

from . import Detection


DEFAULT_STATUSES = ["running", "failed", "broken"]

# Param schema consumed by the shared helper. Alarm modules may re-export
# or extend this. Each value is a dict with keys:
#   type          python type used for the param (float, int, str, list)
#   required      True if this param has no default and must be supplied
#   default       default value when the alarm config omits the key
#   description   human-readable one-liner for the editor help panel
PARAMS: dict[str, dict] = {
    "threshold": {
        "type": float, "required": True,
        "description": "failure-rate threshold (e.g. 0.03 = 3%)",
    },
    "since_days": {
        "type": int, "default": 1,
        "description": "look back this many days into PanDA",
    },
    "username": {
        "type": str,
        "description": "optional task-owner filter (supports % LIKE)",
    },
    "processingtype": {
        "type": str,
        "description": "optional PanDA processingtype filter",
    },
    "min_terminal_jobs": {
        "type": int, "default": 5,
        "description": "ignore tasks with fewer finished+failed jobs than this",
    },
    "statuses": {
        "type": list,
        "description": "task statuses to consider; default running/failed/broken",
    },
}


def task_failure_rate(client, params: dict):
    threshold = float(params["threshold"])
    since_days = int(params.get("since_days", 1))
    username = params.get("username")
    processingtype = params.get("processingtype")
    min_terminal = int(params.get("min_terminal_jobs", 5))
    statuses = params.get("statuses") or DEFAULT_STATUSES

    for status in statuses:
        for t in client.iter_all_tasks(
            days=since_days, status=status,
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
                    f"task {jeditaskid} ({t.get('status') or '?'}) "
                    f"failure rate {cfr*100:.1f}% — {t.get('taskname') or '?'}"
                ),
                body_context=_body_detail(
                    jeditaskid=jeditaskid,
                    taskname=t.get("taskname") or "?",
                    task_status=t.get("status") or "?",
                    task_user=t.get("username") or "?",
                    site=t.get("site") or "?",
                    cfr=cfr, nfailed=nfailed, nfinished=nfinished,
                    nactive=int(t.get("nactive") or 0),
                    threshold=threshold, since_days=since_days,
                    native_failurerate=t.get("failurerate"),
                ),
                extra_data={
                    "metric": f"{cfr*100:.1f}%",
                    "jeditaskid": jeditaskid,
                    "taskname": t.get("taskname"),
                    "status": t.get("status"),
                    "username": t.get("username"),
                    "site": t.get("site"),
                    "computed_failurerate": cfr,
                    "native_failurerate": t.get("failurerate"),
                    "nactive": int(t.get("nactive") or 0),
                    "nfinished": nfinished,
                    "nfailed": nfailed,
                    "threshold": threshold,
                    "since_days": since_days,
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
        f"Owner:       {k['task_user']}\n"
        f"Site:        {k['site']}\n"
        f"\n"
        f"Computed failure rate: {k['cfr']*100:.1f}%  (threshold {k['threshold']*100:.1f}%)\n"
        f"Jobs: nfailed={k['nfailed']}  nfinished={k['nfinished']}  nactive={k['nactive']}\n"
        f"Since: last {k['since_days']} day(s)\n"
        f"{native_line}\n"
        f"\n"
        f"Task page: https://epic-devcloud.org/prod/panda/tasks/{k['jeditaskid']}/\n"
    )
