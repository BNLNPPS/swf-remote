"""
REST client for swf-monitor via SSH tunnel.

Two modes:
- proxy(): forwards a Django request to swf-monitor and returns raw bytes/content-type.
  Used for DataTables AJAX and filter-counts (browser views).
- _get(): fetches clean JSON dicts. Used by MCP tools (future).
"""

import logging
import httpx
from django.conf import settings
from django.http import HttpResponse

logger = logging.getLogger(__name__)

TIMEOUT = 30
UPSTREAM_HEADERS = {'Host': 'pandaserver02.sdcc.bnl.gov'}


def _base():
    return settings.SWF_MONITOR_URL.rstrip('/')


def proxy(request, path):
    """Proxy a request to swf-monitor, return an HttpResponse.

    Forwards HTTP method, query parameters, request body, and authenticated
    user identity (via X-Remote-User header). Returns the upstream response
    as-is (content-type, status code, body) with URL rewriting.
    """
    url = f"{_base()}{path}"
    params = request.GET.dict()
    headers = dict(UPSTREAM_HEADERS)

    # Pass authenticated user identity for attribution on swf-monitor
    if hasattr(request, 'user') and request.user.is_authenticated:
        headers['X-Remote-User'] = request.user.username

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
        # Rewrite upstream paths to match our proxy URL structure
        if b'/swf-monitor/' in body:
            body = body.replace(b'/swf-monitor/', b'/')
        # Rewrite upstream hashed static CSS to our local path
        if b'/static/css/style.' in body:
            import re as _re
            body = _re.sub(rb'/static/css/style\.[a-f0-9]+\.css', b'/static/css/style.css', body)
        # Rewrite pandaserver-doma.cern.ch trf links through our text proxy
        if b'pandaserver-doma.cern.ch/trf/' in body:
            body = body.replace(b'href="https://pandaserver-doma.cern.ch/trf/', b'href="/panda/view-text/?url=https://pandaserver-doma.cern.ch/trf/')
            body = body.replace(b'href=\\"https://pandaserver-doma.cern.ch/trf/', b'href=\\"/panda/view-text/?url=https://pandaserver-doma.cern.ch/trf/')
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


def _get(path, params=None):
    """GET request to swf-monitor, return parsed JSON dict."""
    url = f"{_base()}{path}"
    try:
        resp = httpx.get(url, params=params, timeout=TIMEOUT, verify=False, headers=UPSTREAM_HEADERS)
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
