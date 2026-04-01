"""Middleware to expire stale cookies from pre-subpath deployment."""


class ExpireOldCookiesMiddleware:
    """Delete old csrftoken/sessionid cookies scoped to / on every response.

    After migrating from / to /prod/, browsers still send old cookies.
    This middleware tells the browser to drop them.
    Remove this middleware once enough time has passed (a few weeks).
    """
    OLD_COOKIES = ('csrftoken', 'sessionid')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        for name in self.OLD_COOKIES:
            if name in request.COOKIES:
                response.delete_cookie(name, path='/')
        return response
