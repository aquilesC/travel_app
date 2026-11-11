from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.urls import include, path


@login_not_required
def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz),
    path("accounts/", include("allauth.urls")),
    path("", include("accounts.urls")),
    path("", include("trips.urls")),
]
