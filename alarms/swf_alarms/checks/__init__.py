"""Checks registry.

A check is a callable:  check(client, params) -> iterable[Alarm]
Register by string name in the `REGISTRY` dict. The runner picks checks
from config by their `kind` field and calls them.

Contract:
  - Must not raise on transient failure (log + yield nothing).
  - Must not send notifications directly. Notification is the dispatcher's job.
  - Must set `Alarm.check_name` to `params['_check_name']` (the check
    config name injected by the runner), NOT the check kind. This is how
    firings from two check configs of the same kind (e.g. one for Sakib,
    one for EIC catch-all) stay separate.
  - `dedupe_key` scopes within a single check. Include only the subject
    entity (task id, queue, etc.) — `(check_name, dedupe_key)` together
    form the unique firing key.
"""
from __future__ import annotations

from .failure_rate import task_failure_rate


REGISTRY = {
    "task_failure_rate": task_failure_rate,
}
