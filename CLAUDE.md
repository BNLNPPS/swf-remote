# swf-remote

Start from the SWF workspace guide, `../swf-testbed/CLAUDE.md`
(<https://github.com/BNLNPPS/swf-testbed/blob/main/CLAUDE.md>): the
system, the workspace, how to work, production and collaboration. This
file adds what is particular to swf-remote, the external face of the
platform at epic-devcloud.org: it consumes swf-monitor's pages, REST
endpoints and MCP server through an SSH tunnel from pandaserver02 at BNL,
and adds devcloud sign-in, per-user tokens and TeamComms.

TeamComms authentication, proxying and deployment: `docs/teamcomms.md`.

## Architecture

- **Web pages**: most (hub, PanDA, PCS, Alarms, System) are full rendered HTML proxied from
  swf-monitor via monitor_client.proxy(), with swf-monitor URLs rewritten to
  local /prod/ paths. The MCP setup page, the tokens page, and the auth
  pages render locally with swf-remote's own base.html. Old local alarm code remains for
  rollback/reference, but live /prod/alarms/ proxies to swf-monitor.
- **MCP relay**: /prod/mcp/ forwards swf-monitor's MCP endpoint through the
  tunnel as the signed-in user; headless clients use per-user tokens
  (remote_app/token_auth.py, docs/live-data-access.md).
- **Data source**: Thin REST endpoints on swf-monitor wrapping panda/queries.py.
- **No local PanDA data**: All data comes from swf-monitor through the tunnel.

## Conventions

Follow swf-monitor conventions: python-decouple, single settings.py, same
URL structure under /panda/.

## Nav

swf-remote holds no nav markup. `base.html` renders `{% monitor_nav %}`,
which takes the nav element from swf-monitor's production hub through the
tunnel (`monitor_client.nav_html`), rewritten and with local auth controls
like every proxied page, cached for a minute. A nav change on the monitor
appears on every devcloud page without a change here.
