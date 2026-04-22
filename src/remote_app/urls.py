from django.urls import path
from . import views

app_name = 'monitor_app'

urlpatterns = [
    path('', views.prod_home, name='home'),
    path('prod/', views.prod_home, name='prod_home'),  # alias for backward compat
    path('testbed/', views.testbed_home, name='testbed_home'),
    path('account/', views.account, name='account'),
    path('about/', views.about, name='about'),

    # PanDA Production Monitor — proxied from swf-monitor
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

    # EIC PanDA Queues — proxied from swf-monitor
    path('panda/epic-queues/', views.epic_queues_list, name='epic_queues_list'),
    path('panda/epic-queues/<str:queue_name>/', views.epic_queue_detail, name='epic_queue_detail'),

    # PCS (Physics Configuration System) — all proxied from swf-monitor
    path('pcs/', views.pcs_proxy, name='pcs_hub'),
    path('pcs/categories/', views.pcs_proxy, name='pcs_categories_list'),
    path('pcs/categories/create/', views.pcs_proxy, name='pcs_category_create'),

    # Tag compose (2-panel browse + create) — before generic tag routes
    path('pcs/tags/<str:tag_type>/compose/', views.pcs_proxy, name='pcs_tag_compose'),
    path('pcs/tags/<str:tag_type>/param-defs/', views.pcs_proxy, name='pcs_tag_param_defs'),

    # Tags
    path('pcs/tags/<str:tag_type>/', views.pcs_proxy, name='pcs_tags_list'),
    path('pcs/tags/<str:tag_type>/datatable/', views.pcs_proxy, name='pcs_tags_datatable_ajax'),
    path('pcs/tags/<str:tag_type>/<int:tag_number>/', views.pcs_proxy, name='pcs_tag_detail'),
    path('pcs/tags/<str:tag_type>/<int:tag_number>/edit/', views.pcs_proxy, name='pcs_tag_edit'),
    path('pcs/tags/<str:tag_type>/<int:tag_number>/delete/', views.pcs_proxy, name='pcs_tag_delete'),
    path('pcs/tags/<str:tag_type>/<int:tag_number>/lock/', views.pcs_proxy, name='pcs_tag_lock'),

    # Datasets
    path('pcs/datasets/compose/', views.pcs_proxy, name='pcs_datasets_compose'),
    path('pcs/datasets/', views.pcs_proxy, name='pcs_datasets_list'),
    path('pcs/datasets/datatable/', views.pcs_proxy, name='pcs_datasets_datatable_ajax'),
    path('pcs/datasets/create/', views.pcs_proxy, name='pcs_dataset_create'),
    path('pcs/datasets/<int:pk>/', views.pcs_proxy, name='pcs_dataset_detail'),
    path('pcs/datasets/<int:pk>/add-block/', views.pcs_proxy, name='pcs_dataset_add_block'),

    # Production Configs
    path('pcs/configs/compose/', views.pcs_proxy, name='pcs_prod_configs_compose'),
    path('pcs/configs/', views.pcs_proxy, name='pcs_configs_list'),
    path('pcs/configs/datatable/', views.pcs_proxy, name='pcs_configs_datatable_ajax'),
    path('pcs/configs/create/', views.pcs_proxy, name='pcs_config_create'),
    path('pcs/configs/<int:pk>/', views.pcs_proxy, name='pcs_config_detail'),
    path('pcs/configs/<int:pk>/edit/', views.pcs_proxy, name='pcs_config_edit'),

    # Production Tasks
    path('pcs/tasks/', views.pcs_proxy, name='pcs_tasks_list'),
    path('pcs/tasks/datatable/', views.pcs_proxy, name='pcs_tasks_datatable_ajax'),
    path('pcs/tasks/compose/', views.pcs_proxy, name='pcs_task_compose'),
    path('pcs/tasks/<int:pk>/', views.pcs_proxy, name='pcs_task_detail'),
    path('pcs/tasks/<int:pk>/delete/', views.pcs_proxy, name='pcs_task_delete'),
    path('pcs/tasks/<int:pk>/commands/', views.pcs_proxy, name='pcs_task_commands'),

    # PCS REST API (catch-all proxy for DRF endpoints)
    path('pcs/api/<path:path>', views.pcs_api_proxy, name='pcs_api_proxy'),

    # PanDA REST API (read-only JSON; catch-all proxy for DRF endpoints)
    path('api/panda/<path:path>', views.panda_api_proxy, name='panda_api_proxy'),

    # Alarm dashboard (entries-backed; see alarm_views.py)
    path('alarms/', views.alarms_dashboard, name='alarms_dashboard'),
    path('alarms/events/<str:event_uuid>/', views.alarm_event_detail,
         name='alarm_event_detail'),
    path('alarms/runs/<str:run_uuid>/<str:entry_id>/',
         views.alarm_run_report, name='alarm_run_report'),
    path('alarms/<str:entry_id>/task/',
         views.alarm_task_history, name='alarm_task_history'),
    path('alarms/teams/new/', views.team_new, name='team_new'),
    path('alarms/teams/create/', views.team_create, name='team_create'),
    path('alarms/teams/<str:at_name>/edit/', views.team_edit, name='team_edit'),
    path('alarms/teams/<str:at_name>/save/', views.team_save, name='team_save'),
    path('alarms/teams/<str:at_name>/versions/<int:version_num>/',
         views.team_version, name='team_version'),
    path('alarms/<str:entry_id>/edit/', views.alarm_config_edit,
         name='alarm_config_edit'),
    path('alarms/<str:entry_id>/save/', views.alarm_config_save,
         name='alarm_config_save'),
    path('alarms/<str:entry_id>/versions/<int:version_num>/',
         views.alarm_config_version, name='alarm_config_version'),
    path('alarms/<str:entry_id>/test/', views.alarm_test, name='alarm_test'),

    # Static assets — proxy from swf-monitor so CSS/JS stays in sync
    path('static/<path:path>', views.static_proxy, name='static_proxy'),
]
