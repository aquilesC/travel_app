"""Who is calling: the website (session cookie + CSRF) or the app (allauth X-Session-Token)."""

from allauth.headless.internal.sessionkit import authenticate_by_x_session_token
from ninja.security import APIKeyHeader, SessionAuth


class AppTokenAuth(APIKeyHeader):
    """allauth's app session token, sent as `X-Session-Token`. No CSRF: browsers don't send it
    automatically. Declared as an apiKey header so the OpenAPI contract is complete (the iOS
    client is generated from it)."""

    param_name = "X-Session-Token"

    def authenticate(self, request, key):
        if not key:
            return None
        found = authenticate_by_x_session_token(key)
        if not found:
            return None
        user = found[0]
        if not user.is_active:
            return None
        request.user = user
        request.auth_method = "token"
        return user


class WebSessionAuth(SessionAuth):
    """The website's own JavaScript. Unsafe methods need the CSRF token."""

    def __call__(self, request):
        user = super().__call__(request)
        if user is not None:
            request.auth_method = "session"
        return user


app_token = AppTokenAuth()
web_session = WebSessionAuth(csrf=True)
default_auth = [app_token, web_session]
