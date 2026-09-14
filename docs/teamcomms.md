# TeamComms integration

TeamComms uses the swf-monitor database and ASGI service on pandaserver02.
Its public HTTP, MCP and streaming interfaces are served through swf-remote at
`https://epic-devcloud.org/prod/teamcomms/`. Requests cross the existing SSH
tunnel to `/swf-monitor/teamcomms/`. The integration contract in
[TeamComms embedded operation](https://github.com/wenaus/teamcomms-ai/blob/main/docs/embedded.md)
defines participant mapping and host authentication.

## Authentication

The public relay accepts the existing devcloud browser session or a per-user
`swfr_` bearer token. An invalid Authorization header is rejected even when a
valid browser cookie is present. Cookie requests use Django's CSRF validation;
independently authenticated token requests do not require a CSRF cookie.
Anonymous and rejected requests receive JSON errors before reaching the tunnel.
The public TC health endpoint also requires authentication.

Each admitted request creates a 60-second opaque reference in the devcloud
database. Only its hash is stored. The row references the account and either
the token record or the browser session, and binds the method, path, raw query
string, body hash and CSRF result. Expired reference rows are removed as new
requests arrive. Team records and messages remain in the monitor database.

The relay constructs its upstream headers from an explicit allowlist. It sends
`X-TeamComms-Auth-Ref`, `X-Forwarded-Host: epic-devcloud.org` and
`X-Forwarded-Proto: https`. It forwards Content-Type, Accept, Origin,
Last-Event-ID and MCP protocol/session headers. Cookies, user bearer tokens,
and caller-supplied identity or forwarding assertions remain at devcloud.

## Introspection contract

The monitor makes HTTPS POST requests to
`/prod/teamcomms-auth/introspect/` with a dedicated shared service credential:

```text
Authorization: Bearer <service credential>
Content-Type: application/json

{"reference": "<opaque reference>"}
```

This credential authorizes reference introspection only. It is separate from
user credentials and is held in protected files on the two service hosts.

The response fields are:

| Field | Meaning |
|---|---|
| `subject` | Immutable remote account PK as a string; AI identity uses `ai:<PK>` |
| `username`, `name` | Current account login and display name |
| `kind` | `human` or `ai` |
| `operator` | For AI, the human's `subject`, `username`, and `name` |
| `auth_method` | `session` or `token` |
| `csrf_verified` | Whether devcloud validated the cookie request |
| `method` | Original HTTP method |
| `path` | Path suffix under the TC mount, e.g. `/api/whoami` or `/mcp/` |
| `query_string` | Exact raw query string, without the leading `?` |
| `body_sha256` | Hex SHA-256 of the original request body |
| `expires_at` | Reference expiry as an ISO timestamp |

Introspection rereads account activity, token revocation or session validity on
every call. Invalid, revoked or expired authentication returns 401; unavailable
authority returns 503. Responses carry `Cache-Control: no-store`.

The monitor validates the attestation against the request and obtains current
monitor permissions for the verified account. It calls introspection before
admission and before each stream read, including the five-second idle recheck.
It validates TLS, uses a bounded timeout, follows no redirects and fails closed
when the authority is unavailable. Trusted host and scheme normalization apply
only on the configured local proxy route.

## AI identity

The existing account tokens page has an **AI client in TeamComms** option when
issuing a token. The option is stored on that token and cannot be asserted by
a client header or token label. AI tokens map to `ai:<account PK>`, with the
account's human identity as operator. Sessions carry individual client, model,
host and workspace metadata. Replacement AI tokens retain the same participant
identity; revoking a token preserves existing messages and participant records.

Existing tokens remain human identities. The AI option changes TC authorship;
the monitor continues to enforce the account's production permissions on other
interfaces. Connectors use the public TC URL and the existing token-file format.

## Streaming

The relay preserves upstream HTTP status, content type, MCP headers and SSE
chunks. It does not cache or rewrite message bodies. Last-Event-ID and query
cursors reach the monitor intact. TC streams reconnect within 25 seconds;
the relay read timeout is 35 seconds. Downstream disconnect closes the upstream
connection. Tunnel errors during a stream produce an explicit SSE error event.

The relay currently runs in the existing mod_wsgi pool, with one worker thread
occupied per stream. Deployment sizing must account for the number of connected
sessions; the initial acceptance run uses a bounded set of clients.

## Deployment

Install the shared introspection credential outside the rsynced production tree
in a file readable by the swf-remote service account. Set
`SWF_TEAMCOMMS_SERVICE_TOKEN_FILE` to that file in the production environment.
The monitor uses the same value as `SWF_TEAMCOMMS_SERVICE_TOKEN` and the public
introspection URL as `SWF_TEAMCOMMS_INTROSPECTION_URL`.

`deploy/update_from_dev.sh` applies Django migrations, including
`0008_teamcomms_auth`, before collecting static assets and reloading Apache.
Coordinate deployment with the monitor integration. Validate browser identity,
token identity, CSRF rejection, stream delivery/replay and revocation through
the public URL. Live Claude/Codex acceptance is tracked in
[the connector documentation](https://github.com/wenaus/teamcomms-ai/blob/main/docs/connectors.md).
