"""Stable anonymous source and request identities for the SWF proxy hop."""

import re
import secrets
import uuid

from django.conf import settings
from django.core import signing


SOURCE_COOKIE_NAME = 'swf_source_prod'
SOURCE_COOKIE_SALT = 'swf-remote-source-v1'
SOURCE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60
SOURCE_ID_RE = re.compile(r'^[0-9a-f]{32}$')


def _source_id(request):
    signed_value = request.COOKIES.get(SOURCE_COOKIE_NAME, '')
    if signed_value:
        try:
            value = signing.loads(signed_value, salt=SOURCE_COOKIE_SALT)
        except signing.BadSignature:
            value = ''
        if isinstance(value, str) and SOURCE_ID_RE.fullmatch(value):
            return value, False
    return secrets.token_hex(16), True


class ProxyIdentityMiddleware:
    """Attach trusted proxy metadata and persist an anonymous source id.

    The source id is an observability label, not authentication or
    authorization. Authenticated user identity remains request.user and the
    X-Remote-User tunnel header.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        source_id, set_cookie = _source_id(request)
        request.swf_source_id = source_id
        request.swf_request_id = uuid.uuid4().hex

        response = self.get_response(request)
        response['X-SWF-Request-ID'] = request.swf_request_id
        if set_cookie:
            response.set_cookie(
                SOURCE_COOKIE_NAME,
                signing.dumps(source_id, salt=SOURCE_COOKIE_SALT),
                max_age=SOURCE_COOKIE_MAX_AGE,
                path=settings.FORCE_SCRIPT_NAME or '/',
                secure=not settings.DEBUG,
                httponly=True,
                samesite='Lax',
            )
        return response
