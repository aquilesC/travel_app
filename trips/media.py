"""Media: chunked uploads, management actions and access-checked file serving."""

import hashlib
import json
import mimetypes
import os
import uuid
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.db.models import Max
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from .models import Entry, Media, Upload

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv", ".webm"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".oga", ".wav", ".amr", ".flac"}


def kind_for(filename=None, content_type=None):
    ext = Path(filename or "").suffix.lower()
    if ext in PHOTO_EXT:
        return Media.PHOTO
    if ext in VIDEO_EXT:
        return Media.VIDEO
    if ext in AUDIO_EXT:
        return Media.AUDIO
    major = (content_type or "").split("/")[0]
    return {"image": Media.PHOTO, "video": Media.VIDEO, "audio": Media.AUDIO}.get(major)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def store_original(entry, source_path, filename, *, is_travel_copy=False, content_type=None):
    """Move a finished file into originals/ and create its Media row.

    Returns (media, None) or (None, error message). The source file is consumed
    on success and left alone on error.
    """
    kind = kind_for(filename, content_type)
    if kind is None:
        return None, f"Unsupported file type: {filename}"
    digest = sha256_of(source_path)
    if entry.media.filter(sha256=digest).exists():
        return None, f"{filename} is already attached to this entry."

    ext = Path(filename).suffix.lower()[:10] or mimetypes.guess_extension(content_type or "") or ""
    relative = f"originals/{entry.trip_id}/{uuid.uuid4().hex}{ext}"
    target = Path(settings.MEDIA_ROOT) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    size = Path(source_path).stat().st_size
    os.replace(source_path, target)

    position = (entry.media.aggregate(m=Max("position"))["m"] or 0) + 1
    media = Media(
        entry=entry, kind=kind, original_name=filename[:255], is_travel_copy=is_travel_copy,
        sha256=digest, size_bytes=size, position=position,
    )
    media.original.name = relative
    media.save()

    from .tasks import process_media

    process_media.enqueue(media.pk)
    return media, None


# Chunked upload API (used by static/js/upload.js) ------------------------------

def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


@require_POST
def upload_start(request, pk):
    return _start_upload(request, entry=get_object_or_404(Entry, pk=pk))


@require_POST
def batch_upload_start(request, batch_id):
    from .models import ImportBatch

    batch = get_object_or_404(ImportBatch, pk=batch_id, status=ImportBatch.OPEN)
    return _start_upload(request, batch=batch)


def _start_upload(request, entry=None, batch=None):
    data = _json_body(request)
    filename = str(data.get("filename", ""))[:255]
    try:
        size = int(data.get("size"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Missing file size."}, status=400)
    if not filename or size <= 0:
        return JsonResponse({"error": "Missing file name or size."}, status=400)
    if kind_for(filename) is None:
        return JsonResponse({"error": f"Unsupported file type: {filename}"}, status=400)
    upload = Upload.objects.create(entry=entry, batch=batch, filename=filename, size=size,
                                   created_by=request.user)
    upload.temp_path.parent.mkdir(parents=True, exist_ok=True)
    upload.temp_path.touch()
    return JsonResponse({
        "id": str(upload.id), "received": 0, "chunk_size": settings.UPLOAD_CHUNK_MAX_BYTES,
    })


@require_GET
def upload_status(request, upload_id):
    upload = get_object_or_404(Upload, pk=upload_id, created_by=request.user)
    return JsonResponse({"id": str(upload.id), "received": upload.received, "size": upload.size})


@require_POST
def upload_chunk(request, upload_id):
    upload = get_object_or_404(Upload, pk=upload_id, created_by=request.user)
    try:
        offset = int(request.GET.get("offset", "-1"))
    except ValueError:
        offset = -1
    received = upload.received
    if offset != received:
        # Client is out of sync (e.g. a retried chunk); tell it where to resume.
        return JsonResponse({"error": "offset mismatch", "received": received}, status=409)
    length = int(request.META.get("CONTENT_LENGTH") or 0)
    if length <= 0 or length > settings.UPLOAD_CHUNK_MAX_BYTES:
        return JsonResponse({"error": "Chunk too large or empty."}, status=413)
    if received + length > upload.size:
        return JsonResponse({"error": "More data than announced."}, status=400)

    with open(upload.temp_path, "ab") as fh:
        remaining = length
        while remaining:
            block = request.read(min(remaining, 1024 * 1024))
            if not block:
                break
            fh.write(block)
            remaining -= len(block)
    if remaining:
        # Connection dropped mid-chunk: drop the partial bytes so a retry lines up.
        with open(upload.temp_path, "r+b") as fh:
            fh.truncate(received)
        return JsonResponse({"error": "Incomplete chunk.", "received": received}, status=400)
    return JsonResponse({"received": received + length})


@require_POST
def upload_complete(request, upload_id):
    upload = get_object_or_404(Upload.objects.select_related("entry", "batch"), pk=upload_id,
                               created_by=request.user)
    if upload.received != upload.size:
        return JsonResponse(
            {"error": "Upload incomplete.", "received": upload.received, "size": upload.size},
            status=400,
        )
    if upload.batch_id:
        from .importing import stage_file

        item, error = stage_file(upload.batch, upload.temp_path, upload.filename)
        upload.temp_path.unlink(missing_ok=True)
        upload.delete()
        if error:  # duplicates are skipped, not failures
            return JsonResponse({"skipped": error})
        return JsonResponse({"item_id": item.pk, "sha256": item.sha256, "size": item.size_bytes})

    media, error = store_original(upload.entry, upload.temp_path, upload.filename)
    if error:
        upload.temp_path.unlink(missing_ok=True)
        upload.delete()
        return JsonResponse({"error": error}, status=409)
    upload.delete()
    return JsonResponse({"media_id": media.pk, "sha256": media.sha256, "size": media.size_bytes})


# Management actions (entry editor) ---------------------------------------------

@require_POST
def media_delete(request, pk):
    media = get_object_or_404(Media, pk=pk)
    entry = media.entry
    media.delete()  # files removed by the post_delete signal
    messages.success(request, "Removed.")
    return redirect("entry_edit", pk=entry.pk)


@require_POST
def media_move(request, pk, direction):
    media = get_object_or_404(Media, pk=pk)
    items = list(media.entry.media.order_by("position", "id"))
    index = items.index(media)
    swap = index - 1 if direction == "up" else index + 1
    if 0 <= swap < len(items):
        items[index], items[swap] = items[swap], items[index]
        for position, item in enumerate(items):
            Media.objects.filter(pk=item.pk).update(position=position)
    return redirect("entry_edit", pk=media.entry_id)


@require_POST
def media_cover(request, pk):
    media = get_object_or_404(Media.objects.select_related("entry__trip"), pk=pk, kind=Media.PHOTO)
    trip = media.entry.trip
    trip.cover = media
    trip.save(update_fields=["cover", "updated_at"])
    messages.success(request, "Trip cover set.")
    return redirect("entry_edit", pk=media.entry_id)


@require_POST
def media_retry(request, pk):
    from .tasks import process_media

    media = get_object_or_404(Media, pk=pk)
    media.status, media.error = Media.PENDING, ""
    media.save(update_fields=["status", "error"])
    process_media.enqueue(media.pk)
    return redirect("entry_edit", pk=media.entry_id)


@require_GET
def media_status(request, pk):
    entry = get_object_or_404(Entry, pk=pk)
    return JsonResponse({"media": [
        {"id": m.pk, "status": m.status} for m in entry.media.all()
    ]})


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
    media = get_object_or_404(Media, pk=pk)
    return file_response(media.variant_path(variant))


@login_not_required
@require_GET
def share_media(request, token, pk, variant):
    media = get_object_or_404(
        Media, pk=pk, entry__is_public=True,
        entry__trip__share_token=token, entry__trip__share_enabled=True,
    )
    return file_response(media.variant_path(variant))
