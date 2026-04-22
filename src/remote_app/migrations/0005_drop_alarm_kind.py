"""Drop `data.kind` from alarm configs.

Alarms are snowflakes — each has its own Python module, keyed by
entry_id. There is no shared "kind" library. The Entry row-level `kind`
column remains `'alarm'` (the document kind). This strips `data.kind`
from every alarm config row.

Idempotent; reverse is a no-op.
"""
from __future__ import annotations

from django.db import migrations


CONTEXT_NAME = 'swf-alarms'


def drop_kind(apps, schema_editor):
    Entry = apps.get_model('remote_app', 'Entry')
    qs = Entry.objects.filter(context__name=CONTEXT_NAME, kind='alarm',
                              deleted_at__isnull=True)
    for e in qs:
        data = dict(e.data or {})
        if 'kind' in data:
            data.pop('kind', None)
            e.data = data
            e.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('remote_app', '0004_purge_workinggroup')]
    operations = [migrations.RunPython(drop_kind, noop)]
