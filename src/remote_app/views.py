"""
PanDA monitoring views for swf-remote (epic-devcloud.org).

Most pages proxy full rendered HTML from swf-monitor through the SSH tunnel.
The hub page is rendered locally (devcloud-specific content).
"""

from django.contrib.auth import logout as auth_logout
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from . import monitor_client


# ── Auth ─────────────────────────────────────────────────────────────────────

@csrf_exempt
def logout_view(request):
    """Log out and redirect to home.

    csrf_exempt because all pages are proxied from swf-monitor — the CSRF
    token in the logout form is swf-monitor's, which we can never validate.
    Logout is state-destroying so CSRF risk is negligible (worst case: attacker
    logs the user out).
    """
    auth_logout(request)
    return redirect('/prod/')


# ── Home / Hub ───────────────────────────────────────────────────────────────

def home(request):
    """Root — always production on devcloud."""
    from django.shortcuts import redirect
    from django.urls import reverse
    return redirect(reverse('monitor_app:prod_home'))


def prod_home(request):
    return monitor_client.proxy(request, '/prod/')


def testbed_home(request):
    return monitor_client.proxy(request, '/testbed/')


# ── PanDA pages (proxied from swf-monitor) ──────────────────────────────────

def panda_activity(request):
    return monitor_client.proxy(request, '/panda/activity/')


def panda_jobs_list(request):
    return monitor_client.proxy(request, '/panda/jobs/')


def panda_jobs_datatable_ajax(request):
    return monitor_client.proxy(request, '/panda/jobs/datatable/')


def panda_jobs_filter_counts(request):
    return monitor_client.proxy(request, '/panda/jobs/filter-counts/')


def panda_job_detail(request, pandaid):
    return monitor_client.proxy(request, f'/panda/jobs/{pandaid}/')


def panda_tasks_list(request):
    return monitor_client.proxy(request, '/panda/tasks/')


def panda_tasks_datatable_ajax(request):
    return monitor_client.proxy(request, '/panda/tasks/datatable/')


def panda_tasks_filter_counts(request):
    return monitor_client.proxy(request, '/panda/tasks/filter-counts/')


def panda_task_detail(request, jeditaskid):
    return monitor_client.proxy(request, f'/panda/tasks/{jeditaskid}/')


def panda_errors_list(request):
    return monitor_client.proxy(request, '/panda/errors/')


def panda_errors_datatable_ajax(request):
    return monitor_client.proxy(request, '/panda/errors/datatable/')


def panda_diagnostics_list(request):
    return monitor_client.proxy(request, '/panda/diagnostics/')


def panda_diagnostics_datatable_ajax(request):
    return monitor_client.proxy(request, '/panda/diagnostics/datatable/')


# ── PCS (Physics Configuration System) ─────────────────────────────────────
# All PCS views proxy full rendered HTML from swf-monitor. Single handler
# forwards based on request path — no need for per-view functions.

def pcs_proxy(request, **kwargs):
    """Proxy any PCS page to swf-monitor based on request path."""
    path = request.path_info  # e.g. /pcs/tags/p/compose/ (excludes SCRIPT_NAME)
    return monitor_client.proxy(request, path)


@csrf_exempt
def pcs_api_proxy(request, path):
    """Proxy PCS REST API requests.

    GET is public. Write methods (POST/PATCH/DELETE) require login —
    the user's identity is forwarded to swf-monitor via X-Remote-User.
    CSRF is exempted here because swf-monitor's API uses token auth,
    not session+CSRF.
    """
    if request.method != 'GET' and not request.user.is_authenticated:
        return JsonResponse({'error': 'Login required'}, status=401)
    return monitor_client.proxy(request, f'/pcs/api/{path}')


# ── EIC PanDA Queues ──────────────────────────────────────────────────────
# Proxied from swf-monitor (server-rendered pages).

def epic_queues_list(request):
    return monitor_client.proxy(request, '/panda/epic-queues/')


def epic_queue_detail(request, queue_name):
    return monitor_client.proxy(request, f'/panda/epic-queues/{queue_name}/')


def static_proxy(request, path):
    """Proxy static assets from swf-monitor — CSS, JS always in sync."""
    return monitor_client.proxy(request, f'/static/{path}')


def panda_view_text(request):
    """Fetch a PanDA transformation URL — self-extracting zip with embedded scripts.

    Extracts the bash header and all text files from the zip, presents them
    as readable plain text.
    """
    import httpx
    import io
    import zipfile
    url = request.GET.get('url', '')
    if not url or not url.startswith('https://'):
        return HttpResponse('Missing or invalid url parameter', status=400, content_type='text/plain')
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
    except Exception as e:
        return HttpResponse(f'Failed to fetch: {e}', status=502, content_type='text/plain')
    data = resp.content
    parts = []
    # Extract the bash header (text before binary zip data)
    try:
        lines = []
        for line in data.split(b'\n'):
            try:
                lines.append(line.decode('utf-8'))
            except UnicodeDecodeError:
                break
        if lines:
            parts.append(f'=== Shell header ({len(lines)} lines) ===\n')
            parts.append('\n'.join(lines))
    except Exception:
        pass
    # Extract text files from the zip
    try:
        buf = io.BytesIO(data)
        with zipfile.ZipFile(buf) as zf:
            for name in zf.namelist():
                try:
                    content = zf.read(name).decode('utf-8')
                    parts.append(f'\n\n=== {name} ===\n')
                    parts.append(content)
                except (UnicodeDecodeError, KeyError):
                    parts.append(f'\n\n=== {name} (binary, skipped) ===\n')
    except zipfile.BadZipFile:
        if not parts:
            # Not a zip, just serve as text
            parts.append(data.decode('utf-8', errors='replace'))
    return HttpResponse(''.join(parts), content_type='text/plain; charset=utf-8')
