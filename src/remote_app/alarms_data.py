"""Query helpers for the alarm dashboard — ORM over the Entry / EntryVersion
tables. No model logic beyond what the views need.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

from django.db.models import Count, Max

from .models import Entry, EntryContext, EntryVersion


CONTEXT_NAME = 'swf-alarms'
TEAMS_CONTEXT = 'teams'


def _active_alarm_configs_qs():
    return (Entry.objects
            .filter(context_id=CONTEXT_NAME, kind='alarm',
                    archived=False, deleted_at__isnull=True)
            .order_by('timestamp_created'))


def alarm_configs() -> list[dict]:
    out = []
    for e in _active_alarm_configs_qs():
        data = e.data or {}
        out.append({
            'id': e.id,
            'entry_id': data.get('entry_id', ''),
            'name': data.get('entry_id', '').replace('alarm_', '', 1) or e.id[:8],
            'title': e.title,
            'content': e.content,
            'kind': data.get('kind', ''),
            'enabled': bool(data.get('enabled', True)),
            'severity': data.get('severity', 'warning'),
            'recipients': list(data.get('recipients') or []),
            'params': dict(data.get('params') or {}),
            'created': e.timestamp_created,
            'modified': e.timestamp_modified,
            'data': data,
        })
    return out


def get_alarm_config_by_entry_id(entry_id: str) -> Entry | None:
    try:
        return (Entry.objects
                .filter(context_id=CONTEXT_NAME, kind='alarm',
                        data__entry_id=entry_id,
                        deleted_at__isnull=True)
                .first())
    except Entry.DoesNotExist:
        return None


def events_in_window(alarm_entry_id: str, hours: int, limit: int = 500) -> list[dict]:
    """Event entries whose fire_time is within the last N hours.

    Returns dicts with useful denormalised fields for the template.
    """
    event_entry_id = _event_entry_id_for(alarm_entry_id)
    cutoff = time.time() - hours * 3600
    qs = (Entry.objects
          .filter(context_id=CONTEXT_NAME, kind='event',
                  data__entry_id=event_entry_id,
                  archived=False, deleted_at__isnull=True,
                  timestamp_created__gte=cutoff)
          .order_by('-timestamp_created')[:limit])
    return [_event_to_dict(e) for e in qs]


def count_events_in_window(alarm_entry_id: str, hours: int) -> int:
    event_entry_id = _event_entry_id_for(alarm_entry_id)
    cutoff = time.time() - hours * 3600
    return (Entry.objects
            .filter(context_id=CONTEXT_NAME, kind='event',
                    data__entry_id=event_entry_id,
                    archived=False, deleted_at__isnull=True,
                    timestamp_created__gte=cutoff)
            .count())


def active_event_count(alarm_entry_id: str) -> int:
    event_entry_id = _event_entry_id_for(alarm_entry_id)
    return (Entry.objects
            .filter(context_id=CONTEXT_NAME, kind='event',
                    data__entry_id=event_entry_id,
                    archived=False, deleted_at__isnull=True,
                    data__clear_time__isnull=True)
            .count())


def last_fired(alarm_entry_id: str):
    event_entry_id = _event_entry_id_for(alarm_entry_id)
    row = (Entry.objects
           .filter(context_id=CONTEXT_NAME, kind='event',
                   data__entry_id=event_entry_id,
                   archived=False, deleted_at__isnull=True)
           .order_by('-timestamp_created').values('timestamp_created').first())
    return row['timestamp_created'] if row else None


def get_event(event_uuid: str) -> dict | None:
    try:
        e = Entry.objects.get(id=event_uuid, context_id=CONTEXT_NAME,
                              kind='event', deleted_at__isnull=True)
    except Entry.DoesNotExist:
        return None
    return _event_to_dict(e)


def versions_for(entry_uuid: str, limit: int = 50) -> list[dict]:
    qs = (EntryVersion.objects
          .filter(entry_id=entry_uuid)
          .order_by('-version_num')[:limit])
    return [{
        'id': v.id,
        'version_num': v.version_num,
        'title': v.title,
        'content': v.content,
        'data': v.data,
        'changed_by': v.changed_by,
        'timestamp': v.timestamp,
        'preview': v.title or ((v.content or '').splitlines()[0][:120] if v.content else ''),
        'line_count': (v.content or '').count('\n') + (1 if (v.content or '') else 0),
    } for v in qs]


def recent_runs(limit: int = 20) -> list[dict]:
    qs = (Entry.objects
          .filter(context_id=CONTEXT_NAME, kind='engine_run',
                  archived=False, deleted_at__isnull=True)
          .order_by('-timestamp_created')[:limit])
    return [{
        'id': e.id,
        'data': e.data or {},
    } for e in qs]


def engine_health() -> dict:
    """Traffic light for the dashboard header."""
    try:
        last = (Entry.objects
                .filter(context_id=CONTEXT_NAME, kind='engine_run',
                        deleted_at__isnull=True)
                .order_by('-timestamp_created').first())
    except Exception:  # noqa: BLE001
        return {'status': 'unknown', 'reasons': ['DB not reachable.']}

    if last is None:
        return {'status': 'unknown', 'reasons': ['Engine has never run.']}

    data = last.data or {}
    finished = data.get('finished_at')
    reasons: list[str] = []
    status = 'ok'
    if not finished:
        reasons.append('Last engine run did not finish.')
        status = 'warn'
    else:
        age = time.time() - float(finished)
        if age > 15 * 60:
            reasons.append(
                f'Engine stale: last run finished {int(age // 60)} min ago.')
            status = 'bad'
    if data.get('errors'):
        reasons.append(f"Last run had {data['errors']} error(s).")
        status = 'bad'
    if not reasons:
        reasons.append('All checks healthy.')
    return {'status': status, 'reasons': reasons, 'last_run': data,
            'last_run_id': last.id}


# ── internal helpers ───────────────────────────────────────────────────────

# ── teams ────────────────────────────────────────────────────────────────

def list_teams() -> list[dict]:
    """All non-archived teams in the 'teams' context."""
    qs = (Entry.objects
          .filter(context_id=TEAMS_CONTEXT, kind='team',
                  archived=False, deleted_at__isnull=True)
          .order_by('name'))
    out = []
    for e in qs:
        out.append({
            'id': e.id,
            'name': e.name,                       # '@prodops'
            'title': e.title,
            'content': e.content,
            'members': _parse_recipient_tokens(e.content),
            'created': e.timestamp_created,
            'modified': e.timestamp_modified,
        })
    return out


def get_team(at_name: str) -> Entry | None:
    """Fetch a team by its @name. Accepts with-or-without leading '@'."""
    if not at_name:
        return None
    if not at_name.startswith('@'):
        at_name = '@' + at_name
    return (Entry.objects
            .filter(context_id=TEAMS_CONTEXT, kind='team', name=at_name,
                    archived=False, deleted_at__isnull=True)
            .first())


def get_team_by_id(entry_id: str) -> Entry | None:
    try:
        return Entry.objects.get(id=entry_id, context_id=TEAMS_CONTEXT,
                                 kind='team', deleted_at__isnull=True)
    except Entry.DoesNotExist:
        return None


# ── recipient parsing / expansion ────────────────────────────────────────

def _parse_recipient_tokens(raw) -> list[str]:
    """Split a string or list of strings into normalised recipient tokens.

    Tokens may be separated by commas, whitespace, or both. Blank tokens
    dropped. Each token is either an email address or an @<teamname>.
    Returns the list in the order given, deduped (case-insensitive match
    for emails; @names kept as-is).
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        parts: list[str] = []
        for chunk in raw:
            parts.extend(_parse_recipient_tokens(chunk))
        return _dedup_preserve(parts)
    # String path
    s = str(raw)
    # Normalise commas to whitespace for a single split.
    for sep in [',', ';', '\n', '\r', '\t']:
        s = s.replace(sep, ' ')
    tokens = [t.strip() for t in s.split(' ')]
    return _dedup_preserve([t for t in tokens if t])


def _dedup_preserve(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in seq:
        key = t.lower() if '@' in t and not t.startswith('@') else t
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def parse_recipients_input(text) -> list[str]:
    """Public entry point used by views/engine to normalise user input."""
    return _parse_recipient_tokens(text)


def expand_recipients(tokens) -> tuple[list[str], list[str]]:
    """Expand @<team> tokens into their member emails.

    Returns (emails, unresolved). `emails` is the final dedup'd list of
    deliverable addresses. `unresolved` is a list of @<team> tokens that
    didn't resolve — callers should log but not fail on those.
    """
    final: list[str] = []
    unresolved: list[str] = []
    for tok in _parse_recipient_tokens(tokens):
        if tok.startswith('@'):
            team = get_team(tok)
            if team is None or not team.content.strip():
                unresolved.append(tok)
                continue
            final.extend(_parse_recipient_tokens(team.content))
        else:
            final.append(tok)
    return _dedup_preserve(final), unresolved


# ── internal helpers ─────────────────────────────────────────────────────

def _event_entry_id_for(alarm_entry_id: str) -> str:
    if alarm_entry_id.startswith('alarm_'):
        return 'event_' + alarm_entry_id[len('alarm_'):]
    return 'event_' + alarm_entry_id


def _event_to_dict(e: Entry) -> dict:
    data = e.data or {}
    fire_time = data.get('fire_time')
    clear_time = data.get('clear_time')
    return {
        'id': e.id,
        'title': e.title,
        'entry_id': data.get('entry_id'),
        'subject': data.get('subject', ''),
        'dedupe_key': data.get('dedupe_key'),
        'severity': data.get('severity'),
        'fire_time': fire_time,
        'clear_time': clear_time,
        'last_seen': data.get('last_seen'),
        'state': 'active' if clear_time is None else 'cleared',
        'recipients': data.get('recipients') or [],
        'content': e.content,
        'data': data,
        'timestamp_created': e.timestamp_created,
        'timestamp_modified': e.timestamp_modified,
    }
