"""Seed the `swf-alarms` context and two initial alarm configs."""
from __future__ import annotations

import time
import uuid

from django.db import migrations


CONTEXT_NAME = 'swf-alarms'

ALARM_CONFIGS = [
    {
        'title': "PanDA task failure rate — Sakib's tasks",
        'data': {
            'entry_id': 'alarm_panda_failure_rate_sakib',
            'enabled': True,
            'severity': 'warning',
            'recipients': ['srahman1@bnl.gov', 'wenaus@gmail.com'],
            'renotification_window_hours': 24,
            'params': {
                'threshold': 0.03,
                'since_days': 1,
                'username': 'Sakib Rahman',
                'min_terminal_jobs': 5,
            },
        },
        'content': (
            "Alert on PanDA tasks owned by Sakib Rahman whose computed "
            "failure rate exceeds the configured threshold over the "
            "configured window. Threshold, window, and minimum terminal "
            "jobs are in the Check params below.\n"
            "\n"
            "Dashboard: https://epic-devcloud.org/prod/alarms/\n"
        ),
    },
    {
        'title': 'PanDA task failure rate — catch-all',
        'data': {
            'entry_id': 'alarm_panda_failure_rate_eic_all',
            'enabled': True,
            'severity': 'info',
            'recipients': ['wenaus@gmail.com'],
            'renotification_window_hours': 48,
            'params': {
                'threshold': 0.05,
                'since_days': 1,
                'min_terminal_jobs': 5,
            },
        },
        'content': (
            "Catch-all alert on any PanDA task whose computed failure rate "
            "exceeds the configured threshold over the configured window. "
            "Torre-only tuning channel for shaping future per-owner "
            "alarms. Threshold and window live in the Check params below.\n"
        ),
    },
]


def seed(apps, schema_editor):
    Entry = apps.get_model('remote_app', 'Entry')
    EntryContext = apps.get_model('remote_app', 'EntryContext')
    now = time.time()

    ctx, _ = EntryContext.objects.get_or_create(
        name=CONTEXT_NAME,
        defaults={
            'title': 'swf-alarms',
            'description': 'Alarm configs, firings, and engine-run records.',
            'timestamp_created': now,
            'timestamp_modified': now,
        },
    )
    for cfg in ALARM_CONFIGS:
        eid = cfg['data']['entry_id']
        if Entry.objects.filter(context=ctx, kind='alarm',
                                data__entry_id=eid).exists():
            continue
        Entry.objects.create(
            id=str(uuid.uuid4()),
            title=cfg['title'],
            content=cfg['content'],
            kind='alarm',
            context=ctx,
            data=cfg['data'],
            status='active',
            archived=False,
            timestamp_created=now,
            timestamp_modified=now,
        )


def unseed(apps, schema_editor):
    Entry = apps.get_model('remote_app', 'Entry')
    EntryContext = apps.get_model('remote_app', 'EntryContext')
    Entry.objects.filter(context__name=CONTEXT_NAME).delete()
    EntryContext.objects.filter(name=CONTEXT_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [('remote_app', '0001_initial')]
    operations = [migrations.RunPython(seed, unseed)]
