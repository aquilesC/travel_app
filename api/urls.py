from django.urls import URLPattern, URLResolver

from .api import api


def _login_not_required(patterns):
    """The API answers 401 JSON itself; LoginRequiredMiddleware must not redirect to the login page."""
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            _login_not_required(pattern.url_patterns)
        elif isinstance(pattern, URLPattern):
            pattern.callback.login_required = False
    return patterns


urls = api.urls
_login_not_required(urls[0])
