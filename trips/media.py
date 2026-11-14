"""Media: the entry editor's management actions and access-checked file serving.
Uploads go through the API (/api/v1/uploads, trips/services/uploads.py)."""

import mimetypes
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from .access import get_owned
from .models import Media
from .services import media as media_service
from .services.media import kind_for, store_original  # noqa: F401 (re-exported)

# Management actions (entry editor) ---------------------------------------------

@require_POST
def media_delete(request, pk):
    media = get_owned(request.user, Media.objects.select_related("entry__trip"), pk=pk)
    entry_id = media.entry_id
    media_service.delete_media(request.user, media)
    messages.success(request, "Removed.")
    return redirect("entry_edit", pk=entry_id)


@require_POST
def media_move(request, pk, direction):
    media = get_owned(request.user, Media.objects.select_related("entry__trip"), pk=pk)
    media_service.move_media(request.user, media, direction)
    return redirect("entry_edit", pk=media.entry_id)


@require_POST
def media_cover(request, pk):
    media = get_owned(request.user, Media.objects.select_related("entry__trip"), pk=pk, kind=Media.PHOTO)
    media_service.set_cover(request.user, media)
    messages.success(request, "Trip cover set.")
    return redirect("entry_edit", pk=media.entry_id)


@require_POST
def media_retry(request, pk):
    media = get_owned(request.user, Media.objects.select_related("entry__trip"), pk=pk)
    media_service.retry_processing(request.user, media)
    return redirect("entry_edit", pk=media.entry_id)


# Serving ---------------------------------------------------------------------

def file_response(relative_path):
    if not relative_path:
        raise Http404
    full = (Path(settings.MEDIA_ROOT) / relative_path).resolve()
    if Path(settings.MEDIA_ROOT).resolve() not in full.parents:
        raise Http404
    content_type = mimetypes.guess_type(full.name)[0] or "application/octet-stream"
    if settings.MEDIA_ACCEL_REDIRECT:
        response = HttpResponse(content_type=content_type)
        response["X-Accel-Redirect"] = settings.MEDIA_URL + quote(relative_path)
        return response
    if not full.exists():
        raise Http404
    return FileResponse(open(full, "rb"), content_type=content_type)


@require_GET
def serve_media(request, pk, variant):
    media = get_owned(request.user, Media, pk=pk)
    return file_response(media.variant_path(variant))


@login_not_required
@require_GET
def share_media(request, token, pk, variant):
    media = get_object_or_404(
        Media, pk=pk, entry__is_public=True,
        entry__trip__share_token=token, entry__trip__share_enabled=True,
    )
    return file_response(media.variant_path(variant))
