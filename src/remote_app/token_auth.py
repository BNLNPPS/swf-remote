"""Per-user bearer tokens for headless clients (docs/live-data-access.md).

A token is ``swfr_`` followed by 43 URL-safe characters. Only its SHA-256
is stored; the plaintext is shown once, on the account tokens page.
``TokenAuthMiddleware`` turns a valid ``Authorization: Bearer swfr_...``
header into the token's user before the login wall runs, so a token caller
passes the wall and reaches swf-monitor as that user through X-Remote-User.
Tokens are honored only on the MCP relay, so a leaked token is worth the
relay's tool set and nothing else of the account. The token itself never
crosses the tunnel.
"""

import hashlib
import secrets
from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone

TOKEN_PREFIX = 'swfr_'
TOKEN_PATHS = ('/mcp/',)  # path_info prefixes where a token authenticates
LAST_USED_GRANULARITY = timedelta(minutes=1)


def _hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_token(user, label=''):
    """Create a token for ``user``; returns (plaintext, ApiToken)."""
    from .models import ApiToken
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ApiToken.objects.create(
        user=user, label=(label or '')[:100],
        prefix=raw[len(TOKEN_PREFIX):len(TOKEN_PREFIX) + 8],
        key_hash=_hash(raw),
    )
    return raw, token


def resolve_token(raw):
    """The active user behind a plaintext token, else None."""
    from .models import ApiToken
    if not raw.startswith(TOKEN_PREFIX):
        return None
    token = (ApiToken.objects.select_related('user')
             .filter(key_hash=_hash(raw), revoked__isnull=True).first())
    if token is None or not token.user.is_active:
        return None
    now = timezone.now()
    if token.last_used is None or now - token.last_used > LAST_USED_GRANULARITY:
        ApiToken.objects.filter(pk=token.pk).update(last_used=now)
    return token.user


class TokenAuthMiddleware:
    """Authenticate ``Authorization: Bearer swfr_...`` as the token's user.

    Placed after AuthenticationMiddleware and before the login wall, and
    active only under TOKEN_PATHS. A bearer of another form is left alone
    for the upstream to judge; an swf-remote token that is unknown or
    revoked is refused here with 401.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if (auth.startswith('Bearer ' + TOKEN_PREFIX)
                and request.path_info.startswith(TOKEN_PATHS)):
            user = resolve_token(auth[7:].strip())
            if user is None:
                return JsonResponse({'error': 'invalid or revoked token'}, status=401)
            request.user = user
            request.token_auth = True
        return self.get_response(request)
