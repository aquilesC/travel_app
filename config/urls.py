from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.urls import include, path


@login_not_required
def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


ROBOTS_TXT = """\
# Trips is a private journal: please don't crawl or index it.
User-agent: *
Disallow: /
"""


@login_not_required
def robots_txt(request):
    return HttpResponse(ROBOTS_TXT, content_type="text/plain")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz),
    path("accounts/", include("allauth.urls")),
    path("_allauth/", include("allauth.headless.urls")),  # iPhone app login API
    path("robots.txt", robots_txt),
    path("", include("accounts.urls")),
    path("", include("trips.urls")),
]
