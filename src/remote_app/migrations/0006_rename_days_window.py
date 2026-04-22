"""Rename alarm config params: days_window → since_days.

Vocabulary cleanup. Existing alarm Entry rows in context 'swf-alarms'
that have `data.params.days_window` get it moved to
`data.params.since_days`. Value preserved; key renamed. If an alarm
already has `since_days`, this migration leaves it alone.

Idempotent; reverse is a no-op.
"""
from __future__ import annotations

from django.db import migrations


CONTEXT_NAME = 'swf-alarms'


def rename_key(apps, schema_editor):
    Entry = apps.get_model('remote_app', 'Entry')
    qs = Entry.objects.filter(context__name=CONTEXT_NAME, kind='alarm',
                              deleted_at__isnull=True)
    for e in qs:
        data = dict(e.data or {})
        params = dict(data.get('params') or {})
        if 'days_window' not in params:
            continue
        if 'since_days' in params:
            # Both present — trust since_days; drop the legacy key.
            params.pop('days_window', None)
        else:
            params['since_days'] = params.pop('days_window')
        data['params'] = params
        e.data = data
        e.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('remote_app', '0005_drop_alarm_kind')]
    operations = [migrations.RunPython(rename_key, noop)]
