"""
PanDA monitoring views — mirrors swf-monitor's pandamon views.

Page views render the same templates as swf-monitor (shared via symlink).
DataTables AJAX and filter-count views proxy to swf-monitor through the tunnel.
"""

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
    data = monitor_client.study_job(pandaid)
    if 'error' in data:
        return render(request, 'monitor_app/panda_job_detail.html',
                      {'error': data['error'], 'pandaid': pandaid})
    data['pandaid'] = pandaid
    job = data.get('job') or {}
    job['transformation_is_url'] = (job.get('transformation') or '').startswith(('http://', 'https://'))
    return render(request, 'monitor_app/panda_job_detail.html', data)


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
    data = monitor_client.get_task(jeditaskid)
    if isinstance(data, dict) and 'error' in data:
        return render(request, 'monitor_app/panda_task_detail.html',
                      {'error': data['error'], 'jeditaskid': jeditaskid})
    return render(request, 'monitor_app/panda_task_detail.html', {
        'task': data, 'jeditaskid': jeditaskid,
    })


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
