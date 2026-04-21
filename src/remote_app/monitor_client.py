"""
REST client for swf-monitor via SSH tunnel.

Two modes:
- proxy(): forwards a Django request to swf-monitor and returns raw bytes/content-type.
  Used for DataTables AJAX and filter-counts (browser views).
- _get(): fetches clean JSON dicts. Used by MCP tools (future).
"""

import logging
import re
import httpx
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

TIMEOUT = 30
UPSTREAM_HEADERS = {'Host': 'pandaserver02.sdcc.bnl.gov'}

# Replace upstream's <div class="nav-auth">...</div> block with a locally-
# rendered fragment so account/login/logout actions resolve to swf-remote
# (devcloud) URLs, not upstream BNL URLs. Devcloud has its own user table.
NAV_AUTH_RE = re.compile(rb'<div class="nav-auth">.*?</div>', re.DOTALL)

# Inject an "Alarms" link at the end of the production-mode nav section
# (swf-monitor's base.html wraps the production links in a
# <span class="nav-mode nav-production">…</span>). swf-monitor itself
# doesn't know about devcloud alarms, so we surface them here on the
# proxied pages the same way we replace nav-auth.
NAV_ALARMS_LINK = (
    b'<a href="/prod/alarms/" style="margin-left:1em;">Alarms</a>'
)
NAV_PROD_END_RE = re.compile(
    rb'(<span class="nav-mode nav-production">[\s\S]*?)(</span>)',
    re.DOTALL,
)


def _base():
    return settings.SWF_MONITOR_URL.rstrip('/')


def proxy(request, path, service_user=None):
    """Proxy a request to swf-monitor, return an HttpResponse.

    Forwards HTTP method, query parameters, request body, and authenticated
    user identity (via X-Remote-User header). Returns the upstream response
    as-is (content-type, status code, body) with URL rewriting.

    service_user: fallback identity injected as X-Remote-User when no Django
    user is authenticated. Use for service-to-service endpoints that the
    upstream requires IsAuthenticated on (e.g. /api/panda/* viewsets).
    """
    url = f"{_base()}{path}"
    params = request.GET.dict()
    headers = dict(UPSTREAM_HEADERS)

    # Pass authenticated user identity for attribution on swf-monitor
    if hasattr(request, 'user') and request.user.is_authenticated:
        headers['X-Remote-User'] = request.user.username
    elif service_user:
        headers['X-Remote-User'] = service_user

    method = request.method.upper()
    try:
        if method == 'GET':
            resp = httpx.get(url, params=params, timeout=TIMEOUT,
                             verify=False, headers=headers)
        elif method in ('POST', 'PATCH', 'PUT'):
            ct = request.content_type or 'application/octet-stream'
            headers['Content-Type'] = ct
            resp = httpx.request(method, url, params=params, content=request.body,
                                 timeout=TIMEOUT, verify=False, headers=headers)
        elif method == 'DELETE':
            resp = httpx.delete(url, params=params, timeout=TIMEOUT,
                                verify=False, headers=headers)
        else:
            return HttpResponse(
                f'{{"error": "Method {method} not supported"}}',
                status=405, content_type='application/json',
            )

        body = resp.content
        ct = resp.headers.get('content-type', 'application/json')
        # Rewrite upstream paths to match our mount point.
        # /swf-monitor/X → {SCRIPT_NAME}/X (e.g. /prod/X)
        # Preserve absolute URLs to external hosts (e.g. pandaserver02).
        prefix = (settings.FORCE_SCRIPT_NAME or '').encode()
        if b'/swf-monitor/' in body:
            body = body.replace(b'.gov/swf-monitor/', b'.gov/\x00SWF_PRESERVE\x00/')
            body = body.replace(b'/swf-monitor/', prefix + b'/')
            body = body.replace(b'.gov/\x00SWF_PRESERVE\x00/', b'.gov/swf-monitor/')
        # Force production mode — devcloud has no testbed toggle
        if b'navMode' in body:
            body = body.replace(
                b"localStorage.getItem('navMode')",
                b"'production'",
            )
        # Replace upstream's nav-auth section with a locally-rendered fragment.
        # Account management is autonomous on devcloud — login/logout/account
        # all resolve to local URLs against the local user table.
        if b'<div class="nav-auth">' in body:
            local_auth = render_to_string(
                'monitor_app/_nav_auth.html', request=request,
            ).encode('utf-8')
            body = NAV_AUTH_RE.sub(lambda m: local_auth, body, count=1)
        # Inject Alarms link at end of the production-mode nav section.
        if b'nav-mode nav-production' in body and b'/prod/alarms/' not in body:
            body = NAV_PROD_END_RE.sub(
                lambda m: m.group(1) + NAV_ALARMS_LINK + m.group(2),
                body, count=1,
            )
        # Rewrite pandaserver-doma.cern.ch trf links through our text proxy
        if b'pandaserver-doma.cern.ch/trf/' in body:
            body = body.replace(b'href="https://pandaserver-doma.cern.ch/trf/', b'href="' + prefix + b'/panda/view-text/?url=https://pandaserver-doma.cern.ch/trf/')
            body = body.replace(b'href=\\"https://pandaserver-doma.cern.ch/trf/', b'href=\\"' + prefix + b'/panda/view-text/?url=https://pandaserver-doma.cern.ch/trf/')
        return HttpResponse(body, status=resp.status_code, content_type=ct)
    except httpx.ConnectError as e:
        logger.error(f"Cannot reach swf-monitor at {url}: {e}")
        return HttpResponse(
            '{"error": "Cannot reach swf-monitor (tunnel down?)"}',
            status=502, content_type='application/json',
        )
    except Exception as e:
        logger.error(f"Proxy to {url} failed: {e}")
        return HttpResponse(
            f'{{"error": "{e}"}}',
            status=502, content_type='application/json',
        )


def _get(path, params=None, as_user=None):
    """GET request to swf-monitor, return parsed JSON dict.

    `as_user` sets X-Remote-User for TunnelAuthentication on endpoints that
    require auth (e.g. /api/users/). Pass a service username like
    'swf-remote-sync' when running from management commands without a
    Django request context.
    """
    url = f"{_base()}{path}"
    headers = dict(UPSTREAM_HEADERS)
    if as_user:
        headers['X-Remote-User'] = as_user
    try:
        resp = httpx.get(url, params=params, timeout=TIMEOUT, verify=False, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError as e:
        logger.error(f"Cannot reach swf-monitor at {url}: {e}")
        return {'error': 'Cannot reach swf-monitor (tunnel down?)'}
    except httpx.HTTPStatusError as e:
        logger.error(f"swf-monitor {e.response.status_code} for {url}")
        return {'error': f'Upstream error: {e.response.status_code}'}
    except Exception as e:
        logger.error(f"Request to {url} failed: {e}")
        return {'error': str(e)}


# ── Clean data accessors (for MCP, future) ──────────────────────────────────

def get_activity(**kwargs):
    return _get('/api/panda/activity/', kwargs)

def list_jobs(**kwargs):
    return _get('/api/panda/jobs/', kwargs)

def study_job(pandaid):
    return _get(f'/api/panda/jobs/{pandaid}/')

def diagnose_jobs(**kwargs):
    return _get('/api/panda/jobs/diagnose/', kwargs)

def error_summary(**kwargs):
    return _get('/api/panda/jobs/errors/', kwargs)

def list_tasks(**kwargs):
    return _get('/api/panda/tasks/', kwargs)

def get_task(jeditaskid):
    return _get(f'/api/panda/tasks/{jeditaskid}/')


# ── PCS data accessors ────────────────────────────────────────────────────

TAG_TYPE_MAP = {'p': 'physics-tags', 'e': 'evgen-tags', 's': 'simu-tags', 'r': 'reco-tags'}


def list_tags(tag_type, **kwargs):
    endpoint = TAG_TYPE_MAP.get(tag_type, f'{tag_type}-tags')
    return _get(f'/pcs/api/{endpoint}/', kwargs)


def get_tag(tag_type, tag_number):
    endpoint = TAG_TYPE_MAP.get(tag_type, f'{tag_type}-tags')
    return _get(f'/pcs/api/{endpoint}/{tag_number}/')


def list_datasets(**kwargs):
    return _get('/pcs/api/datasets/', kwargs)


def get_dataset(pk):
    return _get(f'/pcs/api/datasets/{pk}/')


def list_prod_configs(**kwargs):
    return _get('/pcs/api/prod-configs/', kwargs)


def get_prod_config(pk):
    return _get(f'/pcs/api/prod-configs/{pk}/')
