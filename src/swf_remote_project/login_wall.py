"""Gate anonymous traffic before it reaches the tunnel.

Proxied pages under /prod/ are rendered by swf-monitor at BNL and reached over
the SSH tunnel. Open cached records and independently authenticated endpoints
are explicit exceptions below. Other anonymous requests are refused here
before they cost an upstream page build.

This runs as middleware rather than a per-view decorator because
remote_app/urls.py ends in catch-all proxy routes, deliberately, so that new
swf-monitor pages need no route here. A decorator would silently miss every
one of them.
"""

from django.conf import settings
from django.contrib.auth.views import redirect_to_login


class LoginWallMiddleware:
    """Send anonymous requests to the login page, except on open paths.

    Paths are matched on path_info, which excludes the /prod script name.
    """

    OPEN_PREFIXES = (
        '/accounts/',   # login, logout, and the GitHub authorize callback
        '/static/',     # without this the login page renders unstyled
        # The computing centre room's live record (swf-monitor
        # docs/COMP_SNAPSHOT.md): read anonymously by the etaverse world;
        # a cached product upstream, so an open read costs no build.
        '/panda/comp/',
        # Validation interface (swf-epicprod EPICPROD_VALIDATION.md): open
        # read-only completion/catalog GETs, and the validation-results POST
        # whose token is validated upstream by swf-monitor.
        '/pcs/api/v1/',
        # REST API documentation (swf-epicprod API_DOCUMENTATION.md): the
        # OpenAPI schema and its Swagger UI / Redoc renderers, open read-only.
        '/api/schema/',
        # MCP relay: refuses anonymous calls itself with a 401 so that a
        # headless client gets JSON, not a login redirect (views.mcp_proxy).
        '/mcp/',
        # Stage-out sweep ingest: same reasoning, a machine caller must get
        # JSON rather than a redirect (views.stageout_sweep_pass, which
        # refuses anything without a token).
        '/api/stageout/',
        # TeamComms views enforce token/session or service authentication and
        # return JSON denials before any tunnel request.
        '/teamcomms/',
    )
    # The landing page: prod_home serves a self-contained local page to
    # anonymous visitors and the proxied hub to everyone else, so it stays
    # reachable without touching the tunnel. Machine clients that poll it for
    # liveness keep their 200.
    OPEN_EXACT = ('/', '/prod/', '/teamcomms-auth/introspect/',
                  # Mattermost slash commands: Mattermost cannot sign in, so
                  # swf-monitor checks the command token in the body and
                  # answers 401 without it (views.mattermost_slash).
                  '/api/slash/jev/', '/api/slash/panda/')

    def __init__(self, get_response):
        self.get_response = get_response

    def is_open(self, path):
        return path in self.OPEN_EXACT or path.startswith(self.OPEN_PREFIXES)

    def __call__(self, request):
        if not request.user.is_authenticated and not self.is_open(request.path_info):
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        return self.get_response(request)
