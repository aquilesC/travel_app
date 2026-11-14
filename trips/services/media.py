"""Media files: storing originals and the editor's management actions."""

import hashlib
import mimetypes
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.db.models import Max

from ..access import ensure_member
from ..models import Media
from .errors import Invalid

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
    on success and left alone on error. Callers check membership first.
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

    from ..tasks import process_media

    process_media.enqueue(media.pk)
    return media, None


def delete_media(actor, media):
    """Files are removed by the post_delete signal."""
    ensure_member(actor, media.entry.trip)
    media.delete()


def move_media(actor, media, direction):
    ensure_member(actor, media.entry.trip)
    items = list(media.entry.media.order_by("position", "id"))
    index = items.index(media)
    swap = index - 1 if direction == "up" else index + 1
    if 0 <= swap < len(items):
        items[index], items[swap] = items[swap], items[index]
        for position, item in enumerate(items):
            Media.objects.filter(pk=item.pk).update(position=position)
        from django.utils import timezone

        type(media.entry).objects.filter(pk=media.entry_id).update(updated_at=timezone.now())


def set_cover(actor, media):
    trip = media.entry.trip
    ensure_member(actor, trip)
    if media.kind != Media.PHOTO:
        raise Invalid("Only photos can be a trip cover.")
    trip.cover = media
    trip.save(update_fields=["cover", "updated_at"])
    return trip


def retry_processing(actor, media):
    from ..tasks import process_media

    ensure_member(actor, media.entry.trip)
    media.status, media.error = Media.PENDING, ""
    media.save(update_fields=["status", "error"])
    process_media.enqueue(media.pk)
