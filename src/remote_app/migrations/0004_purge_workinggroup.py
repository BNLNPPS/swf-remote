"""Purge `workinggroup` from alarm configs.

There is one and only one working group in this deployment: EIC. Filtering
on it carries no signal, so the field is being removed from every alarm
config's `data.params` and from any English prose that mentions EIC/working
group. Title of the catch-all is normalised to "catch-all".

Idempotent: re-running is a no-op. Reverse is a no-op (we don't restore
EIC references).
"""
from __future__ import annotations

from django.db import migrations


CONTEXT_NAME = 'swf-alarms'


TITLE_MAP = {
    'alarm_panda_failure_rate_sakib':
        "PanDA task failure rate — Sakib's tasks",
    'alarm_panda_failure_rate_eic_all':
        'PanDA task failure rate — catch-all',
}


CONTENT_MAP = {
    'alarm_panda_failure_rate_sakib': (
        "Alert on PanDA tasks owned by Sakib Rahman whose computed "
        "failure rate exceeds the configured threshold over the "
        "configured window. Threshold, window, and minimum terminal "
        "jobs are in the Check params below.\n"
        "\n"
        "Dashboard: https://epic-devcloud.org/prod/alarms/\n"
    ),
    'alarm_panda_failure_rate_eic_all': (
        "Catch-all alert on any PanDA task whose computed failure rate "
        "exceeds the configured threshold over the configured window. "
        "Torre-only tuning channel for shaping future per-owner alarms. "
        "Threshold and window live in the Check params below.\n"
    ),
}


def purge(apps, schema_editor):
    Entry = apps.get_model('remote_app', 'Entry')
    qs = Entry.objects.filter(context__name=CONTEXT_NAME, kind='alarm',
                              deleted_at__isnull=True)
    for e in qs:
        data = dict(e.data or {})
        params = dict(data.get('params') or {})
        dirty = False
        if 'workinggroup' in params:
            params.pop('workinggroup', None)
            data['params'] = params
            dirty = True
        eid = data.get('entry_id') or ''
        if eid in TITLE_MAP and e.title != TITLE_MAP[eid]:
            e.title = TITLE_MAP[eid]
            dirty = True
        if eid in CONTENT_MAP and e.content != CONTENT_MAP[eid]:
            e.content = CONTENT_MAP[eid]
            dirty = True
        if dirty:
            e.data = data
            e.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('remote_app', '0003_seed_teams')]
    operations = [migrations.RunPython(purge, noop)]
