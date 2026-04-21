"""Display filters for swf-remote templates.

Ported from swf-monitor/monitor_app/templatetags/swf_fmt.py, reduced to the
filters swf-remote actually uses. Keep this file in step with swf-monitor's
fmt_dt / state_class behavior — same Eastern display, same BigMon _fill
class naming — so cells render identically across the two apps.

Usage: ``{% load swf_fmt %}`` then ``{{ value|fmt_dt }}`` or
``<td class="{{ value|state_class }}">``.
"""
from datetime import datetime, date
from zoneinfo import ZoneInfo

from django import template

register = template.Library()

_EASTERN = ZoneInfo('America/New_York')


@register.filter(name='fmt_dt')
def fmt_dt(value):
    """Format a datetime / ISO string / Unix float as ``YYYYMMDD HH:MM:SS``
    in Eastern.

    Accepts Python datetimes, date objects, ISO strings, and Unix-epoch
    floats / ints (which is what Entry.timestamp_created uses).

    Returns:
        - '' for falsy input
        - the original string if ISO parsing fails
        - formatted string otherwise
    """
    if not value and value != 0:
        return ''
    if isinstance(value, (int, float)):
        try:
            value = datetime.fromtimestamp(float(value), tz=_EASTERN)
        except (OSError, OverflowError, ValueError):
            return str(value)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=_EASTERN)
        return value.astimezone(_EASTERN).strftime('%Y%m%d %H:%M:%S')
    if isinstance(value, date):
        return value.strftime('%Y%m%d')
    return str(value)


@register.filter(name='state_class')
def state_class(value):
    """Return the BigMon `_fill` CSS class name for a state value.

    Use as ``<td class="{{ value|state_class }}">…</td>`` to fill the whole
    cell with the state's color per state-colors.css. Lowercased so inputs
    like 'Failed' match ``.failed_fill``. Whitespace and '-' are treated
    as valid characters in the CSS class (so 'in-progress' → 'in-progress_fill').
    """
    if not value:
        return ''
    return f'{str(value).lower()}_fill'
