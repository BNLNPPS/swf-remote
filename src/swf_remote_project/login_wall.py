"""Keep anonymous traffic off the tunnel.

Every page under /prod/ is rendered by swf-monitor at BNL and reached over the
SSH tunnel, so an anonymous request that gets as far as a view costs an
upstream page build. Refusing it here means it never crosses the tunnel at
all, which is the point: enforcing the same rule upstream would still let the
traffic arrive before rejecting it.

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
    )
    # The landing page: prod_home serves a self-contained local page to
    # anonymous visitors and the proxied hub to everyone else, so it stays
    # reachable without touching the tunnel. Machine clients that poll it for
    # liveness keep their 200.
    OPEN_EXACT = ('/', '/prod/')

    def __init__(self, get_response):
        self.get_response = get_response

    def is_open(self, path):
        return path in self.OPEN_EXACT or path.startswith(self.OPEN_PREFIXES)

    def __call__(self, request):
        if not request.user.is_authenticated and not self.is_open(request.path_info):
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        return self.get_response(request)
