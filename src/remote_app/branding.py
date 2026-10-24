"""Browser-tab identity for local and proxied devcloud HTML pages."""
import re


FAVICON_LINKS = (
    b'<link rel="icon" type="image/svg+xml" href="/favicon.svg?v=epic-red-e-1">\n'
    b'<link rel="alternate icon" href="/favicon.ico?v=epic-red-e-1">\n'
)
HEAD_END = re.compile(rb'</head\s*>', re.IGNORECASE)


class DevcloudBrandingMiddleware:
    """Give locally rendered and tunnel-proxied pages the same favicon."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (response.streaming or
                not response.get('Content-Type', '').lower().startswith('text/html') or
                'attachment' in response.get('Content-Disposition', '').lower()):
            return response
        body = response.content
        if b'epic-red-e-1' not in body:
            body, changed = HEAD_END.subn(lambda m: FAVICON_LINKS + m.group(0), body, count=1)
            if changed:
                response.content = body
                if response.has_header('Content-Length'):
                    response['Content-Length'] = str(len(body))
        return response
