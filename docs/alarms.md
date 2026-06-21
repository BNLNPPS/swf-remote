# swf-remote alarms

Historical note: swf-remote no longer owns the live alarm system.

The live alarm dashboard, editor, alarm state, standalone runner, and cron
runtime moved to `swf-monitor` on `pandaserver02`. Current code lives in:

- `swf-monitor/alarms/`
- `swf-monitor/src/monitor_app/alarm_views.py`
- `swf-monitor/src/monitor_app/alarms_data.py`
- `swf-monitor/docs/alarms.md`

Current external behavior:

- `/prod/alarms/...` is proxied by swf-remote to swf-monitor.
- swf-remote preserves the monitor-rendered production header.
- swf-remote replaces only the local auth block.
- The old swf-remote alarm cron is disabled.
- The old swf-remote alarm code and DB rows are retained only for
  rollback/reference. Do not delete them casually.

Historical implementation summary:

- The old runner lived under `swf-remote/alarms/`.
- It stored alarm configs, events, engine runs, and teams in swf-remote's
  generic `Entry` tables.
- The exported cutover state was loaded into swf-monitor.
- Email delivery used AWS SES through `boto3`; the monitor-side runner keeps
  that implementation until BNL mail delivery replaces it.
