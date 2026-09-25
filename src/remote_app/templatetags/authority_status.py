"""{% authority_status as st %}: the signed-in account's membership standing.

Read by the account menu in monitor_app/_nav_auth.html, which swf-remote
renders on every page, proxied or native. The values are the latest sign-in
check (remote_app/authority.py), kept locally so the menu costs no call
upstream.
"""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def authority_status(context):
    user = getattr(context.get('request'), 'user', None) or context.get('user')
    if not user or not user.is_authenticated:
        return None
    from ..authority import github_login
    from ..models import AuthorityStatus

    status = AuthorityStatus.objects.filter(user=user).first()
    login = (status.github if status and status.github else github_login(user)) or ''
    if not login:
        state = 'local'          # no GitHub identity; access is by rights
    elif status and status.failed:
        state = 'failed'
    elif status and status.eic is True:
        state = 'member'
    elif status and status.eic is False:
        state = 'not-member'
    else:
        state = 'unchecked'
    return {
        'state': state,
        'github': login,
        'checked_at': status.checked_at if status else None,
        'failed': status.failed if status else '',
        'failed_at': status.failed_at if status else None,
    }
