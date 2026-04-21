"""Checks registry.

A check is a callable:  check(client, params) -> iterable[Detection]
Register by `kind` string in REGISTRY.

A Detection is a lightweight dataclass the runner uses to drive event-entry
creation/update. The check knows the domain (PanDA tasks, etc.); the runner
owns persistence, email, dedup via (alarm_entry_id, dedupe_key).

Contract:
  - Must not raise on transient failure (log + yield nothing).
  - Must not send notifications directly.
  - `dedupe_key` scopes within a single alarm config. Use the subject
    entity (task id, queue name, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .failure_rate import task_failure_rate


@dataclass
class Detection:
    dedupe_key: str              # per-entity identifier, e.g. "task:35981"
    subject: str                 # short line for email subject + dashboard
    body_context: str            # detail text (appended to alarm config body)
    extra_data: dict = field(default_factory=dict)  # structured context


REGISTRY = {
    "task_failure_rate": task_failure_rate,
}
