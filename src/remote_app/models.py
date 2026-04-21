"""Django models for swf-remote.

Central to this repo: a generic tjai-style `Entry` table that holds any
kind of customization data — alarm configs, alarm firings, engine run
records, and whatever we add next (dashboards, annotations, ad-hoc notes).
One flexible document-DB on top of swf-remote's existing Postgres.

Shape follows tjai (tjai_app/models.py): content + kind + context +
name + JSONField data + priority/status + timestamps + soft-delete,
with `data.entry_id` as a non-unique human-readable slug (a single
entry_id can appear across many rows — e.g. all events for one alarm
share `data.entry_id = 'event_<alarm_name>'`).

Archive policy: `status='archive'` entries are filtered out of live
dashboard lists. Hard-delete via `deleted_at`.
"""
from __future__ import annotations

import time
import uuid

from django.db import models


VALID_KINDS = (
    'alarm',       # alarm configuration
    'event',       # alarm firing (fire_time, clear_time, state in data)
    'engine_run',  # one swf-alarms engine tick, with aggregate counters
    'memory',      # generic note, matches tjai
    'list',        # matches tjai
    'action',      # future: scheduled actions, matches tjai
)

VALID_STATUSES = ('active', 'done', 'blocked', 'failed')


def _new_entry_id() -> str:
    """UUID4 default for Entry.id. Module-level so migrations can serialize it."""
    return str(uuid.uuid4())


class EntryContext(models.Model):
    """Project/topic grouping for entries. Matches tjai Context model."""
    name = models.CharField(max_length=255, primary_key=True)
    title = models.CharField(max_length=255, blank=True, default='')
    description = models.TextField(blank=True, default='')
    timestamp_created = models.FloatField(default=time.time)
    timestamp_modified = models.FloatField(default=time.time)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'entry_context'

    def __str__(self):
        return self.name


class Entry(models.Model):
    """Generic document-store row. See module docstring for the model."""

    id = models.CharField(max_length=36, primary_key=True,
                          default=_new_entry_id)
    content = models.TextField(blank=True, default='')
    kind = models.CharField(max_length=50)
    context = models.ForeignKey(EntryContext, on_delete=models.PROTECT,
                                null=True, blank=True, related_name='entries')
    # `name` is the tjai @-style unique identifier within a context. Not used
    # by alarms but kept so the table is tjai-compatible for future kinds.
    name = models.CharField(max_length=255, null=True, blank=True)
    data = models.JSONField(null=True, blank=True)
    priority = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=50, null=True, blank=True)
    # Explicit archive flag — filters out of live dashboard lists without
    # overloading `status`. Distinct from `deleted_at` (soft delete).
    archived = models.BooleanField(default=False)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='children')
    timestamp_created = models.FloatField(default=time.time)
    timestamp_modified = models.FloatField(default=time.time)
    deleted_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = 'entry'
        constraints = [
            models.UniqueConstraint(
                fields=['context', 'name'],
                condition=models.Q(name__isnull=False),
                name='uniq_context_name',
            ),
        ]
        indexes = [
            models.Index(fields=['kind', '-timestamp_created']),
            models.Index(fields=['context', 'kind', '-timestamp_created']),
            models.Index(fields=['archived']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        slug = (self.data or {}).get('entry_id') or self.name or self.id[:8]
        return f'{self.kind}:{slug}'

    @property
    def entry_id(self) -> str | None:
        """Human-readable slug from data.entry_id (non-unique by design)."""
        return (self.data or {}).get('entry_id')


class EntryVersion(models.Model):
    """Immutable snapshot of an Entry's content + data at a point in time.

    Written by a pre_save signal on Entry whenever content or substantive
    data changes. Matches tjai's versioning pattern — UI can render a
    history table and load a prior version for re-editing.
    """
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE,
                              related_name='versions')
    version_num = models.IntegerField()
    content = models.TextField(blank=True, default='')
    data = models.JSONField(null=True, blank=True)
    changed_by = models.CharField(max_length=100, default='unknown')
    timestamp = models.FloatField(default=time.time)

    class Meta:
        db_table = 'entry_version'
        constraints = [
            models.UniqueConstraint(fields=['entry', 'version_num'],
                                    name='uniq_entry_version_num'),
        ]
        indexes = [models.Index(fields=['entry', '-timestamp'])]
