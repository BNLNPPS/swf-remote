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
    """Proxy a GET request to swf-monitor, return an HttpResponse.

    Forwards all query parameters. Returns the upstream response as-is
    (content-type, status code, body).
    """
    url = f"{_base()}{path}"
    params = request.GET.dict()
    try:
        resp = httpx.get(url, params=params, timeout=TIMEOUT, verify=False, headers=UPSTREAM_HEADERS)
        body = resp.content
        ct = resp.headers.get('content-type', 'application/json')
        # Rewrite upstream paths to match our proxy URL structure
        if b'/swf-monitor/' in body:
            body = body.replace(b'/swf-monitor/', b'/')
        # Rewrite upstream hashed static CSS to our local path
        if b'/static/css/style.' in body:
            import re as _re
            body = _re.sub(rb'/static/css/style\.[a-f0-9]+\.css', b'/static/css/style.css', body)
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
