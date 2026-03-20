from django.urls import path
from . import views

app_name = 'monitor_app'

urlpatterns = [
    path('', views.home, name='home'),

    # PanDA Production Monitor — mirrors swf-monitor's URL structure
    path('panda/', views.panda_hub, name='panda_hub'),
    path('panda/activity/', views.panda_activity, name='panda_activity'),

    path('panda/jobs/', views.panda_jobs_list, name='panda_jobs_list'),
    path('panda/jobs/datatable/', views.panda_jobs_datatable_ajax, name='panda_jobs_datatable_ajax'),
    path('panda/jobs/filter-counts/', views.panda_jobs_filter_counts, name='panda_jobs_filter_counts'),
    path('panda/jobs/<int:pandaid>/', views.panda_job_detail, name='panda_job_detail'),

    path('panda/tasks/', views.panda_tasks_list, name='panda_tasks_list'),
    path('panda/tasks/datatable/', views.panda_tasks_datatable_ajax, name='panda_tasks_datatable_ajax'),
    path('panda/tasks/filter-counts/', views.panda_tasks_filter_counts, name='panda_tasks_filter_counts'),
    path('panda/tasks/<int:jeditaskid>/', views.panda_task_detail, name='panda_task_detail'),

    path('panda/errors/', views.panda_errors_list, name='panda_errors_list'),
    path('panda/errors/datatable/', views.panda_errors_datatable_ajax, name='panda_errors_datatable_ajax'),

    path('panda/diagnostics/', views.panda_diagnostics_list, name='panda_diagnostics_list'),
    path('panda/diagnostics/datatable/', views.panda_diagnostics_datatable_ajax, name='panda_diagnostics_datatable_ajax'),

    path('panda/view-text/', views.panda_view_text, name='panda_view_text'),
]
