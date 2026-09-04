"""The MCP tool set served on the external face (docs/live-data-access.md).

The relay forwards only the tools named here: tools/list results are
filtered to the set and a tools/call for any other name is refused before
it crosses the tunnel. The set is the read-only tools plus one write,
ai_propose_ping, which creates a proposal that takes effect only when a
person accepts it on the alarm dashboard; it is the way a named collaborator
raises an obligation from outside. Not served: the testbed tools (swf_*),
which control and inspect internal processes; the PCS intake and lifecycle
mutations, driven by the production bot; ai_decide_proposal, whose approve
executes the proposal; and epic_register_ai_assessment, written by the
assessment services. A new monitor tool reaches the outside only when it is
added here.
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
        # PanDA production, read-only
        'panda_get_activity', 'panda_list_jobs', 'panda_diagnose_jobs',
        'panda_list_tasks', 'panda_error_summary', 'panda_study_job',
        'panda_list_queues', 'panda_get_queue', 'panda_resource_usage',
        'panda_harvester_workers',
        # Physics Configuration System, reads
        'pcs_list_tags', 'pcs_get_tag', 'pcs_search_tags',
        'pcs_dataset_list', 'pcs_dataset_get', 'pcs_data_provenance',
        'pcs_prodtask_list', 'pcs_prodtask_get', 'pcs_prodtask_artifact',
        # Campaigns and the action stream
        'epicprod_campaign_status', 'epicprod_list_actions',
        # Snapper operational history
        'snapper_latest', 'snapper_state_at', 'snapper_component_history',
        'snapper_changes_between', 'snapper_context_around', 'snapper_series',
        'snapper_cut_summary',
        # AI content and proposals: reads, and the one write, proposing a ping
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
