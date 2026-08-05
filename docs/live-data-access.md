# Live-data access and public cache policy

## Purpose

`epic-devcloud.org` provides open access to ePIC monitoring information while
the authoritative monitoring application and its data sources run on protected
infrastructure. Some automated clients conceal their identity, ignore crawler
exclusions, and traverse many expensive monitor pages concurrently. An
anonymous crawl must not be able to trigger enough live work to exhaust the
swf-monitor WSGI pool.

The access policy separates public visibility from data freshness. Public users
can read cached monitoring information without an account. Current information
and cache refreshes require an authenticated Django account.

## Access policy

Requests fall into three classes:

- **Authenticated users** may request current information. Their requests may
  run live queries, rebuild cached material, and replace the public cached
  result.
- **Anonymous users** may receive an existing cached result. Their requests
  must never populate or refresh a cache or execute the expensive data assembly
  that the cache protects.
- **Machine clients** that require current information use an authenticated
  service identity. Fixed health and status clients must not depend on a
  User-Agent allowlist for authorization.

Authenticated users are not subject to a traffic limit unless observed use
shows that one is needed. The existing exclusions for self-identified crawlers
remain in place as an inexpensive first filter.

## Cache contract

The cache may remain in swf-monitor. A cached database read and response render
is substantially less expensive than rebuilding a PCS or PanDA page. Moving
the cache to swf-remote is not required unless measured cached-response load
later shows a need for it.

Each cacheable request follows this contract:

1. An authenticated request may compute a current result and update the cache.
2. An anonymous cache hit returns the stored result without starting live work.
3. An anonymous request for a stale result receives that result with a visible
   data timestamp. Staleness does not authorize a refresh.
4. An anonymous cache miss receives a concise explanation and a login link. It
   does not cause cache population.

Freshness and retention are separate. A result may become stale while remaining
available for anonymous use. Cache expiry must therefore not silently remove
the last usable public result when the intended behavior is to serve it as
stale.

The policy applies to all expensive read surfaces, including HTML pages,
DataTables requests, JSON endpoints, filter counts, and other browser-initiated
requests. Protecting only the initial HTML response is insufficient because a
cached page may issue additional live requests after loading.

Cache keys must be bounded and canonical. Arbitrary query parameters must not
create new anonymous cache entries or turn a cache miss into live work. Each
cacheable route defines the query parameters that are part of its public cache
identity.

Authenticated or personalized content must never be exposed through the public
cache. A public cached representation contains only material suitable for an
anonymous response.

## Component responsibilities

### swf-remote

- Authenticates Django users and forwards only locally established user
  identity to swf-monitor.
- Rejects known self-identified crawlers before proxying.
- Preserves the anonymous, authenticated-user, and authenticated-service
  distinction across the proxy boundary.
- Adds trusted tunnel metadata for traffic correlation:
  `X-Remote-Access`, `X-Remote-Request-ID`, `X-Remote-Client`, and
  `X-Remote-User-Agent`. The anonymous client identifier is a signed
  observability cookie and grants no access.
- Presents login links and cache status consistently in proxied responses.

### swf-monitor

- Owns the expensive page and data construction paths and their caches.
- Enforces cached-only access for anonymous proxy requests.
- Allows authenticated users and service identities to refresh cached data.
- Retains the last usable public result when it is allowed to be served stale.
- Publishes cache and request observations for operational monitoring.

Tunnel metadata is trusted only on localhost requests arriving through the SSH
tunnel. `X-Remote-User` remains the sole proxy header that establishes a Django
user identity. `X-Remote-Access` is the cache-policy classification. An
anonymous read-open API request remains `anonymous` even when swf-remote must
provide a compatibility service username to an upstream API that requires
authentication.

### TJAI CAPCOM

A dedicated `swf-traffic` state reports whether the access policy is operating
normally. Its compact status includes current upstream activity, anonymous
cache behavior, live refresh activity, and recent policy violations or
failures. The tile links to the Snapper traffic report.

### Snapper

A `traffic` scope records and displays:

- anonymous and authenticated request rates;
- cache hits, stale responses, and misses;
- authenticated refresh counts and durations;
- current and maximum upstream concurrency;
- response size and route-family fan-out;
- crawler exclusions and access-policy denials.

Time cuts provide source, account or anonymous identity, User-Agent, route
family, and requested-path drilldown. This history determines whether cached
anonymous traffic remains inexpensive and whether additional protection is
needed.

## Operational conditions

The policy is healthy when anonymous live refreshes remain zero and upstream
concurrency stays below the WSGI capacity required for authenticated users.
CAPCOM reports a warning or failure when any of the following occurs:

- an anonymous request reaches a live computation path;
- cache misses or refresh failures make public information unavailable;
- upstream concurrency approaches saturation;
- traffic observation or cache-policy reporting is unavailable.

Traffic signatures remain useful for identifying concealed crawlers and for
forensic drilldown. They are an observation and alerting mechanism under this
policy, rather than the primary control protecting live data construction.
