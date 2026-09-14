"""TeamComms proxy and current devcloud authentication attestations.

The monitor obtains identity through authenticated introspection. Incoming
identity assertions and user credentials are never forwarded to the monitor.
See docs/teamcomms.md for the cross-host contract.
"""

from datetime import timedelta
import hashlib
from importlib import import_module
import json
import logging
import secrets
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from django.contrib.auth import get_user
from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import ApiToken, TeamCommsAuthReference
from .token_auth import TOKEN_PREFIX, _hash

logger = logging.getLogger(__name__)
PUBLIC_PREFIX = '/prod/teamcomms'
REFERENCE_SECONDS = 60
BODY_LIMIT = 65536
TIMEOUT = httpx.Timeout(connect=10, read=35, write=10, pool=10)


def _json(data, status=200):
    response = JsonResponse(data, status=status)
    response['Cache-Control'] = 'no-store'
    return response


def _current_user(reference):
    if reference.token_id is not None:
        token = reference.token
        if token.revoked is not None or token.user_id != reference.user_id:
            return None
        user = token.user
    else:
        store = import_module(settings.SESSION_ENGINE).SessionStore(reference.session_key)
        user = get_user(SimpleNamespace(session=store))
    if not user.is_authenticated or not user.is_active or user.pk != reference.user_id:
        return None
    return user


@csrf_exempt
def introspect(request):
    """Return current identity to the monitor's dedicated service credential."""
    expected = settings.SWF_TEAMCOMMS_SERVICE_TOKEN
    if not expected:
        return _json({'error': 'TeamComms authentication unavailable'}, 503)
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if not secrets.compare_digest(auth, 'Bearer ' + expected):
        return _json({'error': 'Service authentication required'}, 401)
    if request.method != 'POST':
        return _json({'error': 'POST required'}, 405)
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > 1024:
            return _json({'error': 'Request too large'}, 413)
        body = request.body
        if len(body) > 1024:
            return _json({'error': 'Request too large'}, 413)
        data = json.loads(body)
        raw = data.get('reference') if isinstance(data, dict) else None
        if not isinstance(raw, str) or len(raw) != 64:
            return _json({'error': 'Invalid authentication reference'}, 401)
        reference = TeamCommsAuthReference.objects.select_related('token__user').filter(
            key_hash=_hash(raw), expires_at__gt=timezone.now(),
        ).first()
        if reference is None:
            return _json({'error': 'Expired or invalid authentication reference'}, 401)
        user = _current_user(reference)
        if user is None:
            return _json({'error': 'Authentication revoked or expired'}, 401)
        human = {'subject': str(user.pk), 'username': user.username,
                 'name': user.get_full_name() or user.username}
        identity = dict(human, kind='human')
        if reference.token_id is not None and reference.token.teamcomms_ai:
            identity.update(subject='ai:' + str(user.pk), kind='ai',
                            name=human['name'] + ' AI', operator=human)
        return _json(dict(identity,
            auth_method='token' if reference.token_id is not None else 'session',
            csrf_verified=reference.csrf_verified,
            method=reference.method, path=reference.path,
            query_string=reference.query_string, body_sha256=reference.body_sha256,
            expires_at=reference.expires_at.isoformat()))
    except (ValueError, RequestDataTooBig):
        return _json({'error': 'Invalid introspection request'}, 400)
    except Exception as error:
        logger.error('TeamComms introspection unavailable (%s)', type(error).__name__)
        return _json({'error': 'Authentication authority unavailable'}, 503)


def _authenticated_request(request):
    """Resolve a token explicitly, or require a current browser session and CSRF."""
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth:
        if not auth.startswith('Bearer ' + TOKEN_PREFIX):
            return None, _json({'error': 'A devcloud bearer token is required'}, 401)
        token = ApiToken.objects.select_related('user').filter(
            key_hash=_hash(auth[7:].strip()), revoked__isnull=True,
            user__is_active=True,
        ).first()
        if token is None:
            return None, _json({'error': 'Invalid or revoked token'}, 401)
        request.user = token.user
        return token, None
    if not request.user.is_authenticated or not request.user.is_active:
        return None, _json({'error': 'Sign in or supply a devcloud bearer token'}, 401)
    # The outer view is exempt so bearer calls need no cookie CSRF. Validate
    # cookie calls with the ordinary Django middleware and a non-exempt view.
    csrf = CsrfViewMiddleware(lambda req: HttpResponse())
    rejection = csrf.process_view(request, lambda req: HttpResponse(), (), {})
    if rejection is not None:
        return None, _json({'error': 'CSRF validation failed'}, 403)
    return None, None


def _response_headers(upstream, response):
    for key in ('Content-Type', 'MCP-Session-Id', 'MCP-Protocol-Version', 'Allow',
                'Retry-After', 'WWW-Authenticate'):
        if key in upstream.headers:
            response[key] = upstream.headers[key]
    response['Cache-Control'] = 'no-store'
    if 'location' in upstream.headers:
        target = urlsplit(upstream.headers['location'])
        prefix = '/swf-monitor/teamcomms'
        if target.path.startswith(prefix + '/') or target.path == prefix:
            response['Location'] = PUBLIC_PREFIX + target.path[len(prefix):]
            if target.query:
                response['Location'] += '?' + target.query
        elif target.path.startswith(PUBLIC_PREFIX + '/') or target.path == PUBLIC_PREFIX:
            response['Location'] = target.path + ('?' + target.query if target.query else '')
    return response


@csrf_exempt
def proxy(request, subpath=''):
    """Relay authenticated TC HTTP/MCP and bounded SSE through the existing tunnel."""
    if not settings.SWF_TEAMCOMMS_SERVICE_TOKEN:
        return _json({'error': 'TeamComms authentication unavailable'}, 503)
    client = None
    upstream = None
    try:
        token, rejection = _authenticated_request(request)
        if rejection is not None:
            return rejection
        if int(request.META.get('CONTENT_LENGTH') or 0) > BODY_LIMIT:
            return _json({'error': 'Request too large'}, 413)
        body = request.body
        if len(body) > BODY_LIMIT:
            return _json({'error': 'Request too large'}, 413)
        # Reject path normalization before building an upstream URL: a TC
        # request must not escape its dedicated authentication boundary.
        if any(part in {'.', '..'} for part in subpath.split('/')) or any(c in subpath for c in '%\\?#'):
            return _json({'error': 'Invalid TeamComms path'}, 400)
        raw = secrets.token_hex(32)
        now = timezone.now()
        TeamCommsAuthReference.objects.create(
            key_hash=_hash(raw), user=request.user, token=token,
            session_key='' if token else request.session.session_key,
            method=request.method, path='/' + subpath,
            query_string=request.META.get('QUERY_STRING', ''),
            body_sha256=hashlib.sha256(body).hexdigest(),
            csrf_verified=token is None,
            expires_at=now + timedelta(seconds=REFERENCE_SECONDS),
        )
        # These are temporary authentication records, not retained team data.
        TeamCommsAuthReference.objects.filter(expires_at__lte=now).delete()
        headers = {
            'Host': 'epic-devcloud.org',
            'X-TeamComms-Auth-Ref': raw,
            'X-Forwarded-Host': 'epic-devcloud.org',
            'X-Forwarded-Proto': 'https',
            'Accept-Encoding': 'identity',
        }
        for key in ('Accept', 'Content-Type', 'Origin', 'Last-Event-ID',
                    'MCP-Protocol-Version', 'MCP-Session-Id'):
            if key in request.headers:
                headers[key] = request.headers[key]
        url = settings.SWF_MONITOR_URL.rstrip('/') + '/teamcomms/' + subpath
        query = request.META.get('QUERY_STRING', '')
        if query:
            url += '?' + query
        client = httpx.Client(timeout=TIMEOUT, verify=False, follow_redirects=False)
        upstream = client.send(client.build_request(request.method, url, headers=headers, content=body), stream=True)
        if upstream.headers.get('content-type', '').split(';', 1)[0] == 'text/event-stream':
            source, connection = upstream, client

            def chunks():
                try:
                    yield from source.iter_raw()
                except httpx.HTTPError as error:
                    logger.error('TeamComms stream failed (%s)', type(error).__name__)
                    yield b'event: error\ndata: {"error":"TeamComms tunnel unavailable","status":502}\n\n'
                finally:
                    source.close()
                    connection.close()

            response = StreamingHttpResponse(chunks(), status=upstream.status_code,
                                             content_type='text/event-stream')
            # Close even when the downstream disconnects before iteration.
            response._resource_closers.extend([source.close, connection.close])
            response['X-Accel-Buffering'] = 'no'
            _response_headers(upstream, response)
            upstream = client = None
            return response
        content = upstream.read()
        return _response_headers(upstream, HttpResponse(content, status=upstream.status_code))
    except (ValueError, RequestDataTooBig):
        return _json({'error': 'Invalid TeamComms request'}, 400)
    except httpx.HTTPError as error:
        logger.error('TeamComms proxy failed (%s)', type(error).__name__)
        return _json({'error': 'TeamComms tunnel unavailable'}, 502)
    except Exception as error:
        logger.error('TeamComms proxy unavailable (%s)', type(error).__name__)
        return _json({'error': 'TeamComms authentication unavailable'}, 503)
    finally:
        if upstream is not None:
            upstream.close()
        if client is not None:
            client.close()
