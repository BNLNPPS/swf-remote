{% autoescape off %}# ePIC Production Monitor MCP endpoint

{{ mcp_url }} is a Model Context Protocol (MCP) server exposing the ePIC
production monitor's tools: PanDA production state, physics configurations,
campaign status, Snapper operational history, alarms, and the JLab and BNL
Rucio catalogs. Transport is HTTP POST JSON-RPC. Each call is authenticated
as the person whose token it carries.

## Setup

1. Sign in at {{ site_url }} with GitHub or a local account.
2. Create a token at {{ tokens_url }}. It is shown once, acts as you, and is
   revoked on the same page.
3. Register the server. Claude Code:

       claude mcp add --transport http swf-devcloud {{ mcp_url }} --header "Authorization: Bearer <token>"

   Tools appear in a new session as mcp__swf-devcloud__*, which is also the
   pattern for the permissions allow list. Any MCP client with HTTP transport
   and a custom Authorization header is configured the same way.
4. Call get_server_instructions first, then swf_list_available_tools.

An assistant performing this setup obtains the token from the person; it is
not fetchable. A POST without a valid token receives 401. GET returns this
page.
{% endautoescape %}
