# swf-alarms (historical swf-remote copy)

This is the old swf-remote alarm engine. The live alarm system moved to
`swf-monitor/alarms` on `pandaserver02`.

Current live state:

- `/prod/alarms/...` proxies to swf-monitor.
- swf-monitor owns the alarm dashboard/editor, DB state, runtime config, and
  cron runner.
- The old swf-remote alarm cron is disabled.
- This directory is retained for rollback/reference only.

Do not install or schedule this runner as part of normal operations. Current
operations documentation is in `swf-monitor/docs/alarms.md`.

Historical notes:

- The old runner stored state in swf-remote's `entry`, `entry_context`, and
  `entry_version` tables.
- The cutover exported that state and imported it into swf-monitor.
- The old email channel used AWS SES through `boto3`, as the monitor-side
  runner still does until BNL mail delivery replaces it.
