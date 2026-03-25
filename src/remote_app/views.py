"""
PanDA monitoring views — mirrors swf-monitor's pandamon views.

Page views render the same templates as swf-monitor (shared via symlink).
DataTables AJAX and filter-count views proxy to swf-monitor through the tunnel.
"""

from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse

from . import monitor_client


DAYS_OPTIONS = [1, 3, 7, 14, 30]


def _get_days(request):
    try:
        return int(request.GET.get('days', 7))
    except (ValueError, TypeError):
        return 7


def _days_context(days):
    return {
        'days': days,
        'days_options': [{'value': d, 'active': d == days} for d in DAYS_OPTIONS],
    }


# ── Column definitions (must match swf-monitor's pandamon.py) ───────────────

JOB_COLUMNS = [
    {'name': 'pandaid', 'title': 'PanDA ID', 'orderable': True},
    {'name': 'jeditaskid', 'title': 'Task ID', 'orderable': True},
    {'name': 'produsername', 'title': 'User', 'orderable': True},
    {'name': 'jobstatus', 'title': 'Status', 'orderable': True},
    {'name': 'computingsite', 'title': 'Site', 'orderable': True},
    {'name': 'transformation', 'title': 'Transformation', 'orderable': True},
    {'name': 'creationtime', 'title': 'Created', 'orderable': True},
    {'name': 'endtime', 'title': 'Ended', 'orderable': True},
    {'name': 'corecount', 'title': 'Cores', 'orderable': True},
]

TASK_COLUMNS = [
    {'name': 'jeditaskid', 'title': 'Task ID', 'orderable': True},
    {'name': 'taskname', 'title': 'Task Name', 'orderable': True},
    {'name': 'status', 'title': 'Status', 'orderable': True},
    {'name': 'username', 'title': 'User', 'orderable': True},
    {'name': 'workinggroup', 'title': 'Working Group', 'orderable': True},
    {'name': 'creationdate', 'title': 'Created', 'orderable': True},
    {'name': 'modificationtime', 'title': 'Modified', 'orderable': True},
    {'name': 'progress', 'title': 'Progress', 'orderable': True},
    {'name': 'failurerate', 'title': 'Failure Rate', 'orderable': True},
]

ERROR_COLUMNS = [
    {'name': 'error_source', 'title': 'Component', 'orderable': False},
    {'name': 'error_code', 'title': 'Code', 'orderable': False},
    {'name': 'error_diag', 'title': 'Diagnostic', 'orderable': False},
    {'name': 'count', 'title': 'Count', 'orderable': False},
    {'name': 'task_count', 'title': 'Tasks', 'orderable': False},
    {'name': 'users', 'title': 'Users', 'orderable': False},
    {'name': 'sites', 'title': 'Sites', 'orderable': False},
]

DIAG_COLUMNS = [
    {'name': 'pandaid', 'title': 'PanDA ID', 'orderable': False},
    {'name': 'jeditaskid', 'title': 'Task ID', 'orderable': False},
    {'name': 'produsername', 'title': 'User', 'orderable': False},
    {'name': 'jobstatus', 'title': 'Status', 'orderable': False},
    {'name': 'computingsite', 'title': 'Site', 'orderable': False},
    {'name': 'errors', 'title': 'Errors', 'orderable': False},
    {'name': 'endtime', 'title': 'Ended', 'orderable': False},
]


# ── Home / Hub ───────────────────────────────────────────────────────────────

def home(request):
    return render(request, 'monitor_app/panda_hub.html')


def panda_hub(request):
    return render(request, 'monitor_app/panda_hub.html')


def panda_activity(request):
    days = _get_days(request)
    data = monitor_client.get_activity(days=days)
    if 'error' in data:
        ctx = {'error': data['error']}
        ctx.update(_days_context(days))
        return render(request, 'monitor_app/panda_activity.html', ctx)
    data.update(_days_context(days))
    return render(request, 'monitor_app/panda_activity.html', data)


# ── Jobs ─────────────────────────────────────────────────────────────────────

def panda_jobs_list(request):
    days = _get_days(request)
    context = {
        'table_title': 'PanDA Jobs',
        'table_description': f'Production jobs from the last {days} days.',
        'ajax_url': reverse('monitor_app:panda_jobs_datatable_ajax'),
        'filter_counts_url': reverse('monitor_app:panda_jobs_filter_counts'),
        'columns': JOB_COLUMNS,
        'filter_fields': [
            {'name': 'status', 'label': 'Status', 'type': 'select'},
            {'name': 'username', 'label': 'User', 'type': 'select'},
            {'name': 'site', 'label': 'Site', 'type': 'select'},
        ],
        'selected_status': request.GET.get('status', ''),
        'selected_username': request.GET.get('username', ''),
        'selected_site': request.GET.get('site', ''),
        'selected_taskid': request.GET.get('taskid', ''),
    }
    context.update(_days_context(days))
    return render(request, 'monitor_app/panda_jobs_list.html', context)


def panda_jobs_datatable_ajax(request):
    return monitor_client.proxy(request, '/panda/jobs/datatable/')


def panda_jobs_filter_counts(request):
    return monitor_client.proxy(request, '/panda/jobs/filter-counts/')


def panda_job_detail(request, pandaid):
    return monitor_client.proxy(request, f'/panda/jobs/{pandaid}/')


# ── Tasks ────────────────────────────────────────────────────────────────────

def panda_tasks_list(request):
    days = _get_days(request)
    context = {
        'table_title': 'PanDA Tasks',
        'table_description': f'JEDI tasks from the last {days} days.',
        'ajax_url': reverse('monitor_app:panda_tasks_datatable_ajax'),
        'filter_counts_url': reverse('monitor_app:panda_tasks_filter_counts'),
        'columns': TASK_COLUMNS,
        'filter_fields': [
            {'name': 'status', 'label': 'Status', 'type': 'select'},
            {'name': 'username', 'label': 'User', 'type': 'select'},
            {'name': 'workinggroup', 'label': 'Working Group', 'type': 'select'},
        ],
        'selected_status': request.GET.get('status', ''),
        'selected_username': request.GET.get('username', ''),
        'selected_workinggroup': request.GET.get('workinggroup', ''),
    }
    context.update(_days_context(days))
    return render(request, 'monitor_app/panda_tasks_list.html', context)


def panda_tasks_datatable_ajax(request):
    return monitor_client.proxy(request, '/panda/tasks/datatable/')


def panda_tasks_filter_counts(request):
    return monitor_client.proxy(request, '/panda/tasks/filter-counts/')


def panda_task_detail(request, jeditaskid):
    return monitor_client.proxy(request, f'/panda/tasks/{jeditaskid}/')


# ── Errors & Diagnostics ────────────────────────────────────────────────────

def panda_errors_list(request):
    days = _get_days(request)
    context = {
        'table_title': 'PanDA Error Summary',
        'table_description': f'Top error patterns across failed jobs in the last {days} days.',
        'ajax_url': reverse('monitor_app:panda_errors_datatable_ajax'),
        'columns': ERROR_COLUMNS,
    }
    context.update(_days_context(days))
    return render(request, 'monitor_app/panda_errors.html', context)


def panda_errors_datatable_ajax(request):
    return monitor_client.proxy(request, '/panda/errors/datatable/')


def panda_diagnostics_list(request):
    days = _get_days(request)
    context = {
        'table_title': 'PanDA Job Diagnostics',
        'table_description': f'Failed jobs with error details from the last {days} days.',
        'ajax_url': reverse('monitor_app:panda_diagnostics_datatable_ajax'),
        'columns': DIAG_COLUMNS,
    }
    context.update(_days_context(days))
    return render(request, 'monitor_app/panda_diagnostics.html', context)


def panda_diagnostics_datatable_ajax(request):
    return monitor_client.proxy(request, '/panda/diagnostics/datatable/')


# ── PCS (Physics Configuration System) ─────────────────────────────────────
# All PCS views proxy full rendered HTML from swf-monitor. The upstream
# response uses swf-monitor's base.html and pcs: URL namespace, with paths
# like /swf-monitor/pcs/... that our proxy() rewrites to /pcs/... .

def pcs_hub(request):
    return monitor_client.proxy(request, '/pcs/')


def pcs_categories_list(request):
    return monitor_client.proxy(request, '/pcs/categories/')


def pcs_tag_compose(request, tag_type):
    return monitor_client.proxy(request, f'/pcs/tags/{tag_type}/compose/')


def pcs_tag_param_defs(request, tag_type):
    return monitor_client.proxy(request, f'/pcs/tags/{tag_type}/param-defs/')


def pcs_tags_list(request, tag_type):
    return monitor_client.proxy(request, f'/pcs/tags/{tag_type}/')


def pcs_tags_datatable_ajax(request, tag_type):
    return monitor_client.proxy(request, f'/pcs/tags/{tag_type}/datatable/')


def pcs_tag_detail(request, tag_type, tag_number):
    return monitor_client.proxy(request, f'/pcs/tags/{tag_type}/{tag_number}/')


def pcs_tag_edit(request, tag_type, tag_number):
    return monitor_client.proxy(request, f'/pcs/tags/{tag_type}/{tag_number}/edit/')


def pcs_datasets_list(request):
    return monitor_client.proxy(request, '/pcs/datasets/')


def pcs_datasets_datatable_ajax(request):
    return monitor_client.proxy(request, '/pcs/datasets/datatable/')


def pcs_dataset_create(request):
    return monitor_client.proxy(request, '/pcs/datasets/create/')


def pcs_dataset_detail(request, pk):
    return monitor_client.proxy(request, f'/pcs/datasets/{pk}/')


def pcs_configs_list(request):
    return monitor_client.proxy(request, '/pcs/configs/')


def pcs_configs_datatable_ajax(request):
    return monitor_client.proxy(request, '/pcs/configs/datatable/')


def pcs_config_create(request):
    return monitor_client.proxy(request, '/pcs/configs/create/')


def pcs_config_detail(request, pk):
    return monitor_client.proxy(request, f'/pcs/configs/{pk}/')


def pcs_config_edit(request, pk):
    return monitor_client.proxy(request, f'/pcs/configs/{pk}/edit/')


def pcs_api_proxy(request, path):
    """Proxy PCS REST API requests (GET only for now)."""
    return monitor_client.proxy(request, f'/pcs/api/{path}')


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
