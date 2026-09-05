"""{% monitor_nav %}: the monitor's nav on a natively rendered page."""

from django import template
from django.utils.safestring import mark_safe

from .. import monitor_client

register = template.Library()


@register.simple_tag(takes_context=True)
def monitor_nav(context):
    """Render the monitor's nav (monitor_client.nav_html) for this request."""
    return mark_safe(monitor_client.nav_html(context['request']).decode('utf-8'))
