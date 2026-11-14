from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.urls import include, path

from api.urls import urls as api_urls


@login_not_required
def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz),
    path("accounts/", include("allauth.urls")),
    path("_allauth/", include("allauth.headless.urls")),
    path("api/v1/", api_urls),
    path("", include("accounts.urls")),
    path("", include("trips.urls")),
]
