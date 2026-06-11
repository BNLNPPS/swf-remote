# swf-remote AI Guidelines

External PanDA monitoring frontend for the ePIC experiment. Consumes
swf-monitor REST endpoints via SSH tunnel from pandaserver02 at BNL.

Sister project to swf-monitor, swf-testbed, swf-common-lib.

## Architecture

- **Web pages**: most (hub, PanDA, PCS) are full rendered HTML proxied from
  swf-monitor via monitor_client.proxy(), with swf-monitor URLs rewritten to
  local /prod/ paths. Only the Alarms pages, account, and auth pages render
  locally with swf-remote's own base.html.
- **MCP server**: Re-exposes PanDA data for LLM access outside BNL.
- **Data source**: Thin REST endpoints on swf-monitor wrapping panda/queries.py.
- **No local PanDA data**: All data comes from swf-monitor through the tunnel.

## Conventions

Follow swf-monitor conventions: python-decouple, single settings.py, same
URL structure under /panda/.
