"""The MCP tool set served on the external face (docs/live-data-access.md).

The external face serves every monitor tool except ai_decide_proposal,
whose approve executes the proposal, and epic_register_ai_assessment,
which belongs to the assessment services. Access is token-secured, and
state-changing tools retain swf-monitor's upstream @requires_authority /
AUTHORITY_GUARDED_TOOLS checks under the proxied caller's identity.

The relay keeps an explicit set: tools/list results are filtered to it and
any other tools/call is refused before crossing the tunnel. Add a new
monitor tool here in the same work unless Torre rules it internal.
"""

import json

from django.http import HttpResponse

_RUCIO = (
    'list_scopes', 'list_dids', 'list_files', 'list_content', 'get_did_metadata',
    'summarize_datasets', 'get_account_limits', 'get_account_usage', 'list_rses',
    'get_rse_usage', 'list_rules', 'get_rule_locks', 'list_file_replicas',
    'extract_scope',
)

EXTERNAL_TOOLS = frozenset(
    [
        'get_server_instructions',
        # PanDA production and crash investigation
        'panda_get_activity', 'panda_list_jobs', 'panda_diagnose_jobs',
        'panda_list_tasks', 'panda_error_summary', 'panda_study_job',
        'panda_list_queues', 'panda_get_queue', 'panda_resource_usage',
        'panda_harvester_workers',
        'panda_segfault_catalog', 'panda_segfault_findings',
        'panda_segfault_signature', 'panda_segfault_finding_set',
        'panda_segfault_reproduce',
        # Physics Configuration System, reads and authority-gated writes
        'pcs_list_tags', 'pcs_get_tag', 'pcs_search_tags',
        'pcs_dataset_list', 'pcs_dataset_get', 'pcs_data_provenance',
        'pcs_prodtask_list', 'pcs_prodtask_get', 'pcs_prodtask_artifact',
        'pcs_dataset_intake', 'pcs_prodtask_intake',
        'pcs_prodtask_link_input', 'pcs_prodtask_set_status',
        # Campaigns and the action stream
        'epicprod_campaign_status', 'epicprod_list_actions', 'epicprod_storage',
        # Testbed state and authority-gated controls
        'swf_check_agent_manager', 'swf_end_execution', 'swf_get_agent',
        'swf_get_ai_memory', 'swf_get_log_entry', 'swf_get_namespace',
        'swf_get_run', 'swf_get_stf_file', 'swf_get_system_state',
        'swf_get_testbed_status', 'swf_get_tf_slice',
        'swf_get_workflow_execution', 'swf_get_workflow_monitor',
        'swf_kill_agent', 'swf_list_agents', 'swf_list_available_tools',
        'swf_list_logs', 'swf_list_messages', 'swf_list_namespaces',
        'swf_list_runs', 'swf_list_stf_files', 'swf_list_tf_slices',
        'swf_list_workflow_definitions', 'swf_list_workflow_executions',
        'swf_list_workflow_monitors', 'swf_record_ai_memory',
        'swf_send_message', 'swf_start_user_testbed', 'swf_start_workflow',
        'swf_stop_user_testbed', 'swf_stop_workflow',
        # Snapper operational history
        'snapper_latest', 'snapper_state_at', 'snapper_component_history',
        'snapper_changes_between', 'snapper_context_around', 'snapper_series',
        'snapper_cut_summary',
        # AI content and proposals
        'epic_get_ai_content', 'ai_list_proposals', 'ai_propose_ping',
    ]
    + [f'jlab_rucio_{s}' for s in _RUCIO]
    + [f'bnl_rucio_{s}' for s in _RUCIO]
)


def _rpc_error(req_id, message):
    body = {'jsonrpc': '2.0', 'id': req_id,
            'error': {'code': -32602, 'message': message}}
    return HttpResponse(json.dumps(body), content_type='application/json')


def refuse_call(body_bytes):
    """A JSON-RPC error response if the request calls a tool outside the
    external set, else None. Unparseable bodies pass through for the
    upstream to answer."""
    try:
        req = json.loads(body_bytes or b'')
    except (ValueError, UnicodeDecodeError):
        return None
    reqs = req if isinstance(req, list) else [req]
    for r in reqs:
        if not isinstance(r, dict) or r.get('method') != 'tools/call':
            continue
        name = (r.get('params') or {}).get('name')
        if name not in EXTERNAL_TOOLS:
            return _rpc_error(r.get('id'),
                              f'tool {name!r} is not served on the external face')
    return None


def filter_tools_list(body_bytes, content_type):
    """Drop tools outside the external set from a tools/list result."""
    if 'json' not in (content_type or ''):
        return body_bytes
    try:
        resp = json.loads(body_bytes)
    except (ValueError, UnicodeDecodeError):
        return body_bytes
    resps = resp if isinstance(resp, list) else [resp]
    changed = False
    for r in resps:
        tools = (r.get('result') or {}).get('tools') if isinstance(r, dict) else None
        if isinstance(tools, list):
            r['result']['tools'] = [t for t in tools if t.get('name') in EXTERNAL_TOOLS]
            changed = True
    return json.dumps(resp).encode() if changed else body_bytes
