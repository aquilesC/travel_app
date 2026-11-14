"""The versioned HTTP API (v4 #21). Mounted at /api/v1/.

Conventions (see api/README.md): JSON in and out, ISO 8601 UTC timestamps,
cursor pagination, `client_id` UUIDs for idempotent creates, one error shape.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from ninja import NinjaAPI, Schema

from . import errors
from .auth import default_auth

API_VERSION = "1"

class TripsNinjaAPI(NinjaAPI):
    def get_openapi_operation_id(self, operation):
        """The endpoint's function name (e.g. `create_entry`): short, stable names for the
        generated iOS client. Function names must be unique across routers."""
        return operation.view_func.__name__


api = TripsNinjaAPI(
    title="Trips API",
    version=API_VERSION,
    description="API for trips.aquiles.me: the website's JavaScript and the iPhone app.",
    urls_namespace="api-v1",
    auth=default_auth,
    docs_decorator=staff_member_required,
)
errors.install(api)


class HealthOut(Schema):
    api_version: str
    server_time: str


@api.get("/health", auth=None, response=HealthOut, tags=["meta"])
def health(request):
    """No login needed. The app compares `server_time` with its own clock."""
    return {"api_version": API_VERSION, "server_time": timezone.now().isoformat()}


def _register_routers():
    from .routers import imports, live, me, positions, trips, uploads, write  # noqa: F401

    api.add_router("/me", me.router)
    api.add_router("", trips.router)
    api.add_router("", uploads.router)
    api.add_router("", imports.router)
    # write.py adds its endpoints to trips.router (imported above for that side effect)
    api.add_router("", positions.router)
    api.add_router("", live.router)


_register_routers()
