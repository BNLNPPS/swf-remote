# Live-data access policy

## Purpose

`epic-devcloud.org` publishes ePIC monitoring information from outside BNL,
while the authoritative monitoring application and its data sources run on
protected infrastructure inside it. Every `/prod/` page is rendered by
swf-monitor and retrieved over the SSH tunnel, so serving a page costs an
upstream page build on `pandaserver02`.

Automated clients conceal their identity, ignore crawler exclusions, and
traverse expensive pages concurrently. One such client enumerated the PCS
physics facet space — tens of thousands of distinct filter combinations, no
two alike — at more than one request per second, exhausting the swf-remote
WSGI pool and, through the shared Apache instance, the unrelated service at
`/doc/`. Address-based blocking did not reach it: the client moved to a
residential proxy network presenting one request per exit address.

Access therefore depends on identity rather than on traffic signatures. A
request that cannot present an account does not reach the tunnel.

## Access policy

Signing in is required for every proxied surface: HTML pages, DataTables
requests, JSON endpoints, filter counts, and the REST proxies. Protecting only
the initial HTML response would be insufficient, because a page issues further
requests after it loads.

Three paths remain open without an account:

- the login page and the GitHub authorization callback, under `/accounts/`;
- static assets, which are proxied and whose absence leaves the login page
  unstyled;
- the landing page at `/prod/`, which is rendered locally rather than proxied.

The landing page identifies the service and offers sign-in. Because it is
local, an anonymous visitor — including a crawler — costs nothing upstream,
and liveness pollers that watch `/prod/` continue to receive a 200 response.

Machine clients that require current information use an authenticated service
identity. Authorization does not depend on a User-Agent allowlist. Signed-in
users are not rate-limited unless observed use shows a need.

## Establishing an account

An account is established either by a local username and password or by
signing in with GitHub, which creates the Django account on first use so that
collaborators need no provisioned credential. Both carry the same authority.

Membership of the `eic` GitHub organization is not a condition of signing in.
Authentication alone supplies the protection the policy needs, because a
crawler does not complete an OAuth flow, whereas an organization test would
exclude collaborators who do not use GitHub.

A GitHub identity whose verified address matches an existing account signs
into that account and links the two, instead of creating a second one. The
match is against verified `EmailAddress` records, with a fallback to the user
record's own address. Two accounts carrying one address are disambiguated by
the verified record. This requires `SOCIALACCOUNT_QUERY_EMAIL`: it otherwise
follows `SOCIALACCOUNT_EMAIL_REQUIRED`, and while off the provider's
`/user/emails` call is skipped, so no address arrives marked verified and no
account can be matched.

### Tokens for headless clients

A command-line client such as Claude Code cannot complete a browser sign-in.
A signed-in person creates a token on the account tokens page
(`/prod/account/tokens/`); it is shown once and stored as a hash. A request
carrying `Authorization: Bearer <token>` is authenticated as that person
before the login wall runs and reaches swf-monitor as that username through
`X-Remote-User`, exactly as a browser request does. The token never crosses
the tunnel. Tokens are revoked on the same page.

The MCP relay at `/prod/mcp/` is the intended consumer. It forwards JSON-RPC
POSTs to swf-monitor's MCP endpoint and refuses an anonymous call with a 401
rather than a login redirect, so the path is open in the login wall while
the view itself keeps anonymous traffic off the tunnel. swf-monitor's
external-access notes describe the contract from its side.

## Sessions

A session lasts 14 days and the window rolls: each request extends expiry, so
continued use keeps a person signed in and only inactivity ends the session.
Django writes the session record only when the session is non-empty, so
anonymous traffic adds no database write. Expired records are not reaped
automatically; `manage.py clearsessions` removes them.

## Component responsibilities

### swf-remote

- Enforces the policy, in `swf_remote_project/login_wall.py`. Enforcement
  belongs here because a request refused at this boundary never crosses the
  tunnel, whereas the same rule applied upstream would admit the traffic
  before rejecting it.
- Runs the check as middleware. `remote_app/urls.py` ends in catch-all proxy
  routes so that new swf-monitor pages need no route definition here; a
  per-view decorator would leave each of them unprotected.
- Authenticates Django users, by local credential or GitHub sign-in, and
  forwards only locally established user identity to swf-monitor.
- Authenticates headless clients by per-user token
  (`remote_app/token_auth.py`), resolving the token to the same user
  identity before the wall runs.
- Adds trusted tunnel metadata for traffic correlation: `X-Remote-Access`,
  `X-Remote-Request-ID`, `X-Remote-Client`, and `X-Remote-User-Agent`. The
  anonymous client identifier is a signed observability cookie and grants no
  access.

### swf-monitor

- Owns the expensive page and data construction paths.
- Establishes user identity from `X-Remote-User`, through
  `TunnelAuthMiddleware`, and treats a request without that header as
  anonymous. Tunnel metadata is trusted only on localhost requests arriving
  through the SSH tunnel. `X-Remote-Access` carries the classification;
  `X-Remote-User` alone establishes identity.
- Needs no change for this policy. Its own users, reaching it directly inside
  the firewall, are unaffected.

## Observability

A Snapper `traffic` scope records anonymous and authenticated request rates,
policy denials, upstream concurrency, response size, route-family fan-out, and
crawler exclusions. Time cuts provide source, account or anonymous identity,
User-Agent, route family, and requested-path drilldown.

A CAPCOM `swf-traffic` state reports whether the policy is operating normally,
linking to the Snapper traffic report. The policy is healthy when no anonymous
request reaches a proxied surface and upstream concurrency stays below the
capacity signed-in users require.

## Public cached access

Anonymous access to cached monitoring information, rather than to nothing, is
a possible later relaxation. It would return an existing cached result to an
anonymous request while reserving live computation and cache refreshes to
signed-in users, and would restore public visibility of monitoring
information without restoring the load that made sign-in necessary.

It depends on conditions that do not hold today. The cache would have to cover
the expensive surfaces rather than selected products, cache keys would have to
be bounded and canonical so that arbitrary query parameters cannot create
entries or turn a miss into live work, expiry would have to retain the last
usable public result for stale service, and no authenticated or personalized
content could enter a public cached representation. Enforcement would move to
swf-monitor, which owns the caches, at the cost of admitting the traffic to
the tunnel before answering it.

## Contingency for anonymous load

The landing page is local and inexpensive, so anonymous traffic no longer
reaches the tunnel regardless of volume. If anonymous request volume later
burdens swf-remote or the ingress itself,
[Anubis](https://github.com/TecharoHQ/anubis) is the preferred contingency at
the public ingress. It applies an automatic JavaScript proof-of-work challenge
and a signed pass cookie, requiring little user interaction but adding an
ingress service, policy, signing key, state, and monitoring burden. It would
apply to anonymous traffic only; signed-in users and service identities bypass
it, and static assets, health endpoints, crawler policy files, and the login
path remain reachable without the challenge.
