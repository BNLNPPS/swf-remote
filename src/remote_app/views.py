"""
PanDA monitoring views for swf-remote (epic-devcloud.org).

Most pages proxy full rendered HTML from swf-monitor through the SSH tunnel.
The hub page is rendered locally (devcloud-specific content).
"""

from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from . import monitor_client
from .monitor_client import CRAWLER_UA_TOKENS


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


@login_required
def account(request):
    """Proxy the unified username page (My Workflows | Account tabs) from
    swf-monitor. The local password_change endpoint stays native — the
    unified page's tunnel-face password section links to it."""
    return monitor_client.proxy(request, request.path_info)


def about(request):
    """About page — proxied from swf-monitor for content consistency."""
    return monitor_client.proxy(request, '/about/')


# ── Home / Hub ───────────────────────────────────────────────────────────────

def home(request):
    """Root — always production on devcloud."""
    from django.shortcuts import redirect
    from django.urls import reverse
    return redirect(reverse('monitor_app:prod_home'))


def prod_home(request):
    # Anonymous visitors get a local page instead of the proxied hub, so the
    # site's front door costs nothing upstream and liveness pollers still see
    # a 200. See swf_remote_project/login_wall.py.
    if not request.user.is_authenticated:
        from django.shortcuts import render
        return render(request, 'landing.html')
    return monitor_client.proxy(request, '/prod/')


def testbed_home(request):
    return monitor_client.proxy(request, '/testbed/')


@csrf_exempt
def ai_proxy(request, **kwargs):
    """Proxy epicprod AI pages from swf-monitor."""
    return monitor_client.proxy(request, request.path_info)


@csrf_exempt
def logs_proxy(request, **kwargs):
    """Proxy swf-monitor log pages from devcloud."""
    return monitor_client.proxy(request, request.path_info)


def compute_usage_proxy(request, **kwargs):
    """Proxy the production compute-usage page and its data endpoint."""
    return monitor_client.proxy(request, request.path_info)


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


def panda_job_payload_log(request, pandaid):
    """Deny crawler-triggered payload-log retrieval."""
    ua = request.META.get('HTTP_USER_AGENT', '')
    if any(token.lower() in ua.lower() for token in CRAWLER_UA_TOKENS):
        return HttpResponse(
            'Automated crawlers may not trigger payload log retrieval.\n',
            status=403,
            content_type='text/plain',
        )
    return monitor_client.proxy(request, f'/panda/jobs/{pandaid}/payload-log/')


def panda_proxy(request, **kwargs):
    """Catch-all: proxy any PanDA monitor page to swf-monitor by request path, so
    swf-remote never drifts from swf-monitor's route list as it grows (mirrors
    pcs_proxy). Authorization is enforced by the monitor per Django user."""
    return monitor_client.proxy(request, request.path_info)


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

@csrf_exempt
def pcs_proxy(request, **kwargs):
    """Proxy any PCS page to swf-monitor based on request path.

    csrf_exempt for the same reason as logout_view and pcs_api_proxy: a proxied
    page carries swf-monitor's CSRF token, which swf-remote can never validate
    against its own cookie. Authorization is enforced by login_required here and
    by swf-monitor per X-Remote-User through the tunnel (swf-monitor in turn
    exempts localhost/tunnel requests from CSRF). Without this, proxied form
    POSTs — e.g. the catalog Update-from-CSV button — are rejected before they
    can reach the tunnel. login_required() preserves this flag via functools.wraps.
    """
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
    if (request.method != 'GET' and not request.user.is_authenticated
            and not request.headers.get('Authorization')):
        return JsonResponse({'error': 'Login required'}, status=401)
    return monitor_client.proxy(request, f'/pcs/api/{path}')


def schema_proxy(request):
    """Proxy the OpenAPI schema and its Swagger UI / Redoc renderers.

    Read-only documentation pages (swf-epicprod API_DOCUMENTATION.md); the
    sidecar-served UI assets arrive through the existing static proxy after
    path rewriting.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'GET only'}, status=405)
    return monitor_client.proxy(request, request.path_info)


def panda_api_proxy(request, path):
    """Proxy PanDA REST API requests to swf-monitor /api/panda/<path>.

    Read-only: GET only. Upstream requires IsAuthenticated, so we inject
    a service identity when no Django user is logged in — the alarm engine
    and other service consumers hit this anonymously from localhost and
    appear to upstream as 'swf-remote-proxy'.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'GET only'}, status=405)
    return monitor_client.proxy(
        request, f'/api/panda/{path}', service_user='swf-remote-proxy'
    )


@login_required
def sse_proxy(request):
    """Stream swf-monitor's SSE relay to the browser for live push.

    A dedicated streaming proxy — the buffering proxy() cannot carry an
    open-ended text/event-stream. Gated by login here (same-origin to devcloud);
    authenticated to swf-monitor by a service token over the tunnel.
    See swf-monitor/docs/SSE_PUSH.md.
    """
    return monitor_client.stream_sse(request, '/api/messages/stream/')


@csrf_exempt
def analysis_proxy(request, **kwargs):
    """Proxy analysis pages from swf-monitor."""
    return monitor_client.proxy(request, request.path_info)


def snapper_proxy(request, **kwargs):
    """Proxy Snapper report and system pages from swf-monitor."""
    return monitor_client.proxy(request, request.path_info)


def system_proxy(request):
    """Proxy the aggregate swf-monitor System page."""
    return monitor_client.proxy(request, '/system/')


def canary_proxy(request, **kwargs):
    """Proxy the Canary site-health page from swf-monitor."""
    return monitor_client.proxy(request, request.path_info)


def runs_proxy(request, **kwargs):
    """Proxy testbed run pages from swf-monitor."""
    return monitor_client.proxy(request, request.path_info)


def workflow_executions_proxy(request, **kwargs):
    """Proxy testbed workflow-execution pages from swf-monitor."""
    return monitor_client.proxy(request, request.path_info)


def internal_only(request, **kwargs):
    """Friendly terminus for any path this proxy does not carry.

    A swf-monitor page without a proxy route used to die as a bare 404
    here; instead, say plainly that the page lives on the internal
    monitor and hand over the direct URL for anyone inside the BNL
    perimeter.
    """
    from django.http import HttpResponse
    from django.utils.html import escape

    path = request.path_info.lstrip('/')
    query = request.META.get('QUERY_STRING') or ''
    internal_url = ('https://pandaserver02.sdcc.bnl.gov/swf-monitor/'
                    + path + (f'?{query}' if query else ''))
    body = f"""
    <div style="max-width:44rem; margin:5rem auto; font-size:1.15rem;
                font-family:system-ui,sans-serif; line-height:1.55;
                padding:0 1rem;">
      <h1 style="font-size:1.5rem;">Internal monitor page</h1>
      <p>This page is not served on the external face. It is available on
         the internal SWF monitor, reachable from inside the BNL network
         with BNL authentication:</p>
      <p><a href="{escape(internal_url)}">{escape(internal_url)}</a></p>
      <p><a href="/prod/">Back to the external monitor</a></p>
    </div>"""
    return HttpResponse(body, status=404)


@csrf_exempt
def alarms_proxy(request, **kwargs):
    """Proxy alarm pages to swf-monitor.

    Alarms now live in swf-monitor. swf-remote keeps its old alarm code in the
    tree for rollback/reference, but no longer serves it locally.
    """
    return monitor_client.proxy(request, request.path_info)


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


# ── MCP relay and API tokens ─────────────────────────────────────────────────

@csrf_exempt
def mcp_proxy(request, subpath=''):
    """Relay the swf-monitor MCP endpoint (docs/live-data-access.md, Tokens).

    GET serves the self-contained setup page, locally and to anyone, as
    markdown, or as HTML inside the site nav when the client accepts it.
    POST is the transport and accepts only an swf-remote token, which
    TokenAuthMiddleware turns into request.user; a browser session is not
    accepted, so this csrf-exempt POST has no cookie-borne caller. The path
    is open in the login wall so a headless client receives JSON rather
    than a login redirect. Calls without a token stop here and never reach
    the tunnel.
    """
    if request.method == 'GET' and not subpath:
        return mcp_setup(request)
    if request.method != 'POST':
        return HttpResponseNotAllowed(['GET', 'POST'])
    if not getattr(request, 'token_auth', False):
        return JsonResponse(
            {'error': 'Authorization required: Bearer <swf-remote token>; GET this URL for setup'},
            status=401)
    return monitor_client.proxy_mcp(request, subpath)


def mcp_setup(request):
    """The MCP setup page: markdown by default, HTML for a browser."""
    from django.template.loader import render_to_string
    from django.urls import reverse
    text = render_to_string('monitor_app/mcp_setup.md', {
        'mcp_url': request.build_absolute_uri(reverse('monitor_app:mcp')),
        'site_url': request.build_absolute_uri(reverse('monitor_app:home')),
        'tokens_url': request.build_absolute_uri(reverse('monitor_app:account_tokens')),
    })
    if 'text/html' in request.headers.get('Accept', ''):
        import markdown
        return render(request, 'monitor_app/mcp_setup.html',
                      {'html': markdown.markdown(text)})
    return HttpResponse(text, content_type='text/markdown; charset=utf-8')


@login_required
def account_tokens(request):
    """Create and revoke the user's API tokens; a new token is shown once."""
    from django.urls import reverse
    from django.utils import timezone
    from .models import ApiToken
    from .token_auth import issue_token
    new_token = None
    if request.method == 'POST':
        revoke_id = request.POST.get('revoke', '')
        if revoke_id.isdigit():
            ApiToken.objects.filter(user=request.user, pk=int(revoke_id),
                                    revoked__isnull=True).update(revoked=timezone.now())
        else:
            new_token, _ = issue_token(request.user, request.POST.get('label', '').strip())
    return render(request, 'monitor_app/account_tokens.html', {
        'tokens': request.user.api_tokens.order_by('-created'),
        'new_token': new_token,
        'mcp_url': request.build_absolute_uri(reverse('monitor_app:mcp')),
    })
