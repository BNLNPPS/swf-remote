"""Seed the 'teams' context + the first team, @prodops.

Teams are Entry rows with kind='team', context='teams', Entry.name='@<team>'.
Entry.content is the whitespace-delimited email list; Entry.title is the
human-readable name. Alarm configs can reference @<team> in their
recipients list; the engine expands at send-time.

Also updates the alarm_panda_failure_rate_sakib config from a hard-coded
(srahman1,wenaus) pair to ['@prodops'] — same membership, one indirection.
"""
from __future__ import annotations

import time
import uuid

from django.db import migrations


CONTEXT_NAME = 'teams'

TEAMS = [
    {
        'name': '@prodops',
        'title': 'Production ops',
        'content': 'srahman1@bnl.gov wenaus@gmail.com',
        'data': {'entry_id': 'team_prodops'},
    },
]


def seed(apps, schema_editor):
    Entry = apps.get_model('remote_app', 'Entry')
    EntryContext = apps.get_model('remote_app', 'EntryContext')
    now = time.time()

    ctx, _ = EntryContext.objects.get_or_create(
        name=CONTEXT_NAME,
        defaults={
            'title': 'Teams',
            'description': (
                'Named recipient aliases. Referenced from alarm configs '
                'and elsewhere as @<teamname>; resolve at send-time to '
                'the whitespace-delimited email list in Entry.content.'
            ),
            'timestamp_created': now,
            'timestamp_modified': now,
        },
    )

    for t in TEAMS:
        if Entry.objects.filter(context=ctx, kind='team', name=t['name']).exists():
            continue
        Entry.objects.create(
            id=str(uuid.uuid4()),
            title=t['title'],
            content=t['content'],
            kind='team',
            context=ctx,
            name=t['name'],
            data=t['data'],
            status='active',
            archived=False,
            timestamp_created=now,
            timestamp_modified=now,
        )

    # Retro-update the Sakib alarm to use @prodops instead of hard-coded
    # (srahman1, wenaus). Same membership; one indirection to edit later.
    sakib_alarm = (Entry.objects
                   .filter(context_id='swf-alarms', kind='alarm',
                           data__entry_id='alarm_panda_failure_rate_sakib')
                   .first())
    if sakib_alarm is not None:
        data = dict(sakib_alarm.data or {})
        if data.get('recipients') != ['@prodops']:
            data['recipients'] = ['@prodops']
            sakib_alarm.data = data
            sakib_alarm.timestamp_modified = now
            sakib_alarm.save()

    # Add renotification_window_hours to any existing alarm config that
    # doesn't have it (feature added after the initial seed applied).
    defaults = {
        'alarm_panda_failure_rate_sakib': 24,
        'alarm_panda_failure_rate_eic_all': 48,
    }
    for alarm in Entry.objects.filter(context_id='swf-alarms', kind='alarm'):
        data = dict(alarm.data or {})
        if 'renotification_window_hours' in data:
            continue
        eid = data.get('entry_id', '')
        data['renotification_window_hours'] = defaults.get(eid, 24)
        alarm.data = data
        alarm.timestamp_modified = now
        alarm.save()


def unseed(apps, schema_editor):
    Entry = apps.get_model('remote_app', 'Entry')
    EntryContext = apps.get_model('remote_app', 'EntryContext')
    Entry.objects.filter(context__name=CONTEXT_NAME).delete()
    EntryContext.objects.filter(name=CONTEXT_NAME).delete()
    # Revert the Sakib alarm's recipients.
    sakib_alarm = (Entry.objects
                   .filter(context_id='swf-alarms', kind='alarm',
                           data__entry_id='alarm_panda_failure_rate_sakib')
                   .first())
    if sakib_alarm is not None:
        data = dict(sakib_alarm.data or {})
        if data.get('recipients') == ['@prodops']:
            data['recipients'] = ['srahman1@bnl.gov', 'wenaus@gmail.com']
            sakib_alarm.data = data
            sakib_alarm.save()


class Migration(migrations.Migration):
    dependencies = [('remote_app', '0002_seed_alarms')]
    operations = [migrations.RunPython(seed, unseed)]
