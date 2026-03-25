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

    # PCS (Physics Configuration System) — proxied from swf-monitor
    path('pcs/', views.pcs_hub, name='pcs_hub'),
    path('pcs/categories/', views.pcs_categories_list, name='pcs_categories_list'),

    # Tag compose (2-panel browse + create) — before generic tag routes
    path('pcs/tags/<str:tag_type>/compose/', views.pcs_tag_compose, name='pcs_tag_compose'),
    path('pcs/tags/<str:tag_type>/param-defs/', views.pcs_tag_param_defs, name='pcs_tag_param_defs'),

    # Tags
    path('pcs/tags/<str:tag_type>/', views.pcs_tags_list, name='pcs_tags_list'),
    path('pcs/tags/<str:tag_type>/datatable/', views.pcs_tags_datatable_ajax, name='pcs_tags_datatable_ajax'),
    path('pcs/tags/<str:tag_type>/<int:tag_number>/', views.pcs_tag_detail, name='pcs_tag_detail'),
    path('pcs/tags/<str:tag_type>/<int:tag_number>/edit/', views.pcs_tag_edit, name='pcs_tag_edit'),

    # Datasets
    path('pcs/datasets/', views.pcs_datasets_list, name='pcs_datasets_list'),
    path('pcs/datasets/datatable/', views.pcs_datasets_datatable_ajax, name='pcs_datasets_datatable_ajax'),
    path('pcs/datasets/create/', views.pcs_dataset_create, name='pcs_dataset_create'),
    path('pcs/datasets/<int:pk>/', views.pcs_dataset_detail, name='pcs_dataset_detail'),

    # Production Configs
    path('pcs/configs/', views.pcs_configs_list, name='pcs_configs_list'),
    path('pcs/configs/datatable/', views.pcs_configs_datatable_ajax, name='pcs_configs_datatable_ajax'),
    path('pcs/configs/create/', views.pcs_config_create, name='pcs_config_create'),
    path('pcs/configs/<int:pk>/', views.pcs_config_detail, name='pcs_config_detail'),
    path('pcs/configs/<int:pk>/edit/', views.pcs_config_edit, name='pcs_config_edit'),

    # PCS REST API (catch-all proxy for DRF endpoints)
    path('pcs/api/<path:path>', views.pcs_api_proxy, name='pcs_api_proxy'),
]
