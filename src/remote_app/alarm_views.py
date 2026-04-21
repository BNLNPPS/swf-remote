"""Alarm dashboard + editor views.

The dashboard lives at /prod/alarms/. It renders:
  1. A top summary table (one row per alarm config) — last-N-hours counts,
     last-fired time.
  2. A per-alarm section for each active config — config metadata + body +
     in-window events + [Edit] link.
  3. A recent-engine-runs table (for engine health visibility).

Editor: /prod/alarms/<alarm_entry_id>/edit/ — CodeMirror on the body
(content), form fields for params/recipients/severity/enabled. Autosave
every 10s via POST; version history rendered inline, click to restore.

Autosave endpoint: POST /prod/alarms/<alarm_entry_id>/autosave/ with JSON
body. Returns {version_num, modified}.

The pre_save signal on Entry (signals.py) owns version snapshotting; these
views never write EntryVersion directly.
"""
from __future__ import annotations

import json
import time

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import alarms_data
from .models import Entry, EntryVersion
from .signals import set_changed_by


# ── dashboard ─────────────────────────────────────────────────────────────

def alarms_dashboard(request):
    try:
        hours = max(1, int(request.GET.get('hours', 24)))
    except (TypeError, ValueError):
        hours = 24

    configs = alarms_data.alarm_configs()

    # Per-config: count + last-fired + in-window events (reversed chron).
    sections = []
    summary_rows = []
    for cfg in configs:
        eid = cfg['entry_id']
        count = alarms_data.count_events_in_window(eid, hours)
        last = alarms_data.last_fired(eid)
        active = alarms_data.active_event_count(eid)
        events = alarms_data.events_in_window(eid, hours, limit=200)
        summary_rows.append({
            'entry_id': eid,
            'name': cfg['name'],
            'title': cfg.get('title', ''),
            'severity': cfg['severity'],
            'enabled': cfg['enabled'],
            'count': count,
            'active': active,
            'last_fired': last,
        })
        sections.append({
            'config': cfg,
            'count': count,
            'active': active,
            'last_fired': last,
            'events': events,
        })

    return render(request, 'monitor_app/alarms.html', {
        'hours': hours,
        'summary_rows': summary_rows,
        'sections': sections,
        'health': alarms_data.engine_health(),
        'recent_runs': alarms_data.recent_runs(limit=20),
    })


# ── event detail ──────────────────────────────────────────────────────────

def alarm_event_detail(request, event_uuid: str):
    event = alarms_data.get_event(event_uuid)
    if event is None:
        return HttpResponse('Event not found', status=404,
                            content_type='text/plain')
    return render(request, 'monitor_app/alarm_event_detail.html', {
        'event': event,
    })


# ── alarm config editor ───────────────────────────────────────────────────

def _require_alarm(entry_id: str) -> Entry | None:
    return alarms_data.get_alarm_config_by_entry_id(entry_id)


def alarm_config_edit(request, entry_id: str):
    """GET: render CodeMirror editor for an alarm config."""
    alarm = _require_alarm(entry_id)
    if alarm is None:
        return HttpResponse(f'Alarm config {entry_id} not found',
                            status=404, content_type='text/plain')

    versions = alarms_data.versions_for(alarm.id, limit=50)

    data = alarm.data or {}
    return render(request, 'monitor_app/alarm_config_edit.html', {
        'alarm': alarm,
        'alarm_entry_id': entry_id,
        'title': alarm.title or '',
        'content': alarm.content or '',
        'line_count': (alarm.content or '').count('\n') + 1,
        'data_json': json.dumps({
            'enabled': bool(data.get('enabled', True)),
            'severity': data.get('severity', 'warning'),
            'recipients': list(data.get('recipients') or []),
            'kind': data.get('kind', ''),
            'params': dict(data.get('params') or {}),
        }, indent=2, sort_keys=True),
        'versions_json': json.dumps(versions, default=str),
    })


@csrf_exempt  # editor posts JSON; token mismatch handled by auth
@require_POST
def alarm_config_save(request, entry_id: str):
    """POST: save edits to an alarm config. JSON body:
        {
          "content": "...",
          "data": { enabled, severity, recipients, kind, params },
          "autosave": true|false   (optional; marks changed_by=autosave)
        }
    Returns {version_num, modified}.
    """
    alarm = _require_alarm(entry_id)
    if alarm is None:
        return JsonResponse({'error': 'not found'}, status=404)

    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError as e:
        return JsonResponse({'error': f'bad json: {e}'}, status=400)

    new_content = payload.get('content')
    new_title = payload.get('title')
    new_partial = payload.get('data') or {}
    if new_content is None:
        new_content = alarm.content
    if new_title is None:
        new_title = alarm.title

    # Merge partial edits onto existing data, preserving entry_id.
    existing_data = dict(alarm.data or {})
    for k in ('enabled', 'severity', 'recipients', 'params', 'kind'):
        if k in new_partial:
            existing_data[k] = new_partial[k]
    if 'entry_id' not in existing_data:
        existing_data['entry_id'] = entry_id  # keep slug stable

    changed_by = 'autosave' if payload.get('autosave') else 'web_ui'
    if request.user.is_authenticated:
        changed_by = f"{changed_by}:{request.user.username}"
    set_changed_by(changed_by)

    alarm.title = new_title
    alarm.content = new_content
    alarm.data = existing_data
    alarm.timestamp_modified = time.time()
    alarm.save()

    # Report the new latest version number (signal may or may not have
    # snapshotted depending on whether the change was substantive).
    latest = (EntryVersion.objects.filter(entry=alarm)
              .order_by('-version_num').values('version_num').first())
    return JsonResponse({
        'version_num': latest['version_num'] if latest else 0,
        'modified': alarm.timestamp_modified,
    })


def alarm_config_version(request, entry_id: str, version_num: int):
    """GET: return a specific version's content+data as JSON (for restore)."""
    alarm = _require_alarm(entry_id)
    if alarm is None:
        return JsonResponse({'error': 'not found'}, status=404)
    try:
        v = EntryVersion.objects.get(entry_id=alarm.id, version_num=version_num)
    except EntryVersion.DoesNotExist:
        return JsonResponse({'error': 'version not found'}, status=404)
    return JsonResponse({
        'version_num': v.version_num,
        'title': v.title,
        'content': v.content,
        'data': v.data,
        'changed_by': v.changed_by,
        'timestamp': v.timestamp,
    })
