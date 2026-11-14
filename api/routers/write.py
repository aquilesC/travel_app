"""Write API (v4 #24): entries (incl. posts from the app), chapters, GPX tracks."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from ninja import Field, File, Form, Schema
from ninja.files import UploadedFile

from trips.access import get_owned, get_trip
from trips.models import Chapter, Entry, Track
from trips.services import chapters as chapter_service
from trips.services import entries as entry_service
from trips.services import tracks as track_service
from trips.services import uploads as upload_service
from trips.services.errors import Invalid

from ..errors import ApiError
from ..schemas import ChapterOut, EntryOut, entry_out
from .trips import entries_qs, router  # same router: Ninja merges methods per path only within one


class EntryIn(Schema):
    occurred_at: datetime | None = Field(None, description="When it happened (default: now). Include the UTC offset.")
    body: str = Field("", description="Markdown.")
    place_name: str = Field("", max_length=200)
    latitude: float | None = None
    longitude: float | None = None
    is_public: bool = True
    chapter_id: int | None = Field(None, description="Default: the trip's current chapter.")
    upload_ids: list[UUID] = Field([], description="Completed detached uploads to attach, in order.")
    client_id: UUID | None = Field(None, description="Makes retries safe: the same id returns the same entry.")


class EntryPatch(Schema):
    occurred_at: datetime | None = None
    body: str | None = None
    place_name: str | None = Field(None, max_length=200)
    latitude: float | None = None
    longitude: float | None = None
    is_public: bool | None = None
    chapter_id: int | None = None
    upload_ids: list[UUID] = Field([], description="More uploads to attach.")


class ChapterIn(Schema):
    title: str = Field(min_length=1, max_length=200)
    make_current: bool = Field(False, description="New posts from the app and WhatsApp go into it.")


class ChapterPatch(Schema):
    title: str = Field(min_length=1, max_length=200)


class MoveIn(Schema):
    direction: Literal["up", "down"]


class CurrentChapterIn(Schema):
    chapter_id: int | None


class TrackOut(Schema):
    id: int
    name: str
    mode: str
    chapter_id: int | None


def _decimal(value):
    return None if value is None else Decimal(f"{value:.6f}")


def _chapter(trip, chapter_id):
    if chapter_id is None:
        return None
    chapter = trip.chapters.filter(pk=chapter_id).first()
    if chapter is None:
        raise Invalid({"chapter_id": ["No such chapter in this trip."]})
    return chapter


def _check_date(trip, when):
    day = timezone.localtime(when, trip.tz).date()
    if not trip.start_date - timedelta(days=1) <= day <= trip.end_date + timedelta(days=1):
        raise Invalid({"occurred_at": ["Outside the trip's dates."]})


def _source(request):
    return Entry.SOURCE_APP if getattr(request, "auth_method", "") == "token" else Entry.SOURCE_WEB


@router.post("/trips/{trip_id}/entries", response={200: EntryOut, 201: EntryOut})
def create_entry(request, trip_id: int, payload: EntryIn):
    """Post an entry. From the app (token auth) `source` is "app". Media: upload first with
    `trip_id` set (detached), then list the upload ids here."""
    user = request.user
    trip = get_trip(user, trip_id)
    if payload.client_id:
        existing = entries_qs().filter(author=user, client_id=payload.client_id).first()
        if existing:
            return 200, entry_out(existing)
    data = payload.dict(exclude_unset=True)
    occurred_at = payload.occurred_at or timezone.now()
    if occurred_at.tzinfo is None:
        raise Invalid({"occurred_at": ["Include the UTC offset."]})
    _check_date(trip, occurred_at)
    chapter = _chapter(trip, payload.chapter_id) if "chapter_id" in data else trip.current_chapter
    with transaction.atomic():
        entry = entry_service.create_entry(
            user, trip, source=_source(request), occurred_at=occurred_at, body=payload.body,
            place_name=payload.place_name, latitude=_decimal(payload.latitude),
            longitude=_decimal(payload.longitude), is_public=payload.is_public, chapter=chapter)
        if payload.client_id:
            Entry.objects.filter(pk=entry.pk).update(client_id=payload.client_id)
        if payload.upload_ids:
            upload_service.claim_uploads(user, entry, payload.upload_ids)
    return 201, entry_out(entries_qs().get(pk=entry.pk))


@router.patch("/entries/{entry_id}", response=EntryOut)
def update_entry(request, entry_id: int, payload: EntryPatch):
    """Change some fields; fields left out stay as they are."""
    user = request.user
    entry = get_owned(user, Entry.objects.select_related("trip"), pk=entry_id)
    data = payload.dict(exclude_unset=True)
    fields = {k: data[k] for k in ("body", "place_name", "is_public") if k in data and data[k] is not None}
    if "occurred_at" in data and data["occurred_at"] is not None:
        _check_date(entry.trip, data["occurred_at"])
        fields["occurred_at"] = data["occurred_at"]
    for key in ("latitude", "longitude"):
        if key in data:
            fields[key] = _decimal(data[key])
    if "chapter_id" in data:
        fields["chapter"] = _chapter(entry.trip, data["chapter_id"])
    with transaction.atomic():
        entry_service.update_entry(user, entry, **fields)
        if payload.upload_ids:
            upload_service.claim_uploads(user, entry, payload.upload_ids)
    return entry_out(entries_qs().get(pk=entry.pk))


@router.delete("/entries/{entry_id}", response={204: None})
def delete_entry(request, entry_id: int):
    entry_service.delete_entry(request.user, get_owned(request.user, Entry.objects.select_related("trip"), pk=entry_id))
    return 204, None


# Chapters --------------------------------------------------------------------------

def _chapter_out(chapter):
    return {"id": chapter.pk, "title": chapter.title, "position": chapter.position}


@router.post("/trips/{trip_id}/chapters", response={201: ChapterOut})
def create_chapter(request, trip_id: int, payload: ChapterIn):
    trip = get_trip(request.user, trip_id)
    chapter = chapter_service.create_chapter(request.user, trip, payload.title, make_current=payload.make_current)
    return 201, _chapter_out(chapter)


@router.patch("/chapters/{chapter_id}", response=ChapterOut)
def rename_chapter(request, chapter_id: int, payload: ChapterPatch):
    chapter = get_owned(request.user, Chapter.objects.select_related("trip"), pk=chapter_id)
    return _chapter_out(chapter_service.rename_chapter(request.user, chapter, payload.title))


@router.post("/chapters/{chapter_id}/move", response=list[ChapterOut])
def move_chapter(request, chapter_id: int, payload: MoveIn):
    """Swap with the neighbour above or below. Returns the trip's chapters in order."""
    chapter = get_owned(request.user, Chapter.objects.select_related("trip"), pk=chapter_id)
    chapter_service.move_chapter(request.user, chapter, payload.direction)
    return [_chapter_out(c) for c in chapter.trip.chapters.all()]


@router.delete("/chapters/{chapter_id}", response={204: None})
def delete_chapter(request, chapter_id: int):
    """Its entries and tracks are kept, without a chapter."""
    chapter = get_owned(request.user, Chapter.objects.select_related("trip"), pk=chapter_id)
    chapter_service.delete_chapter(request.user, chapter)
    return 204, None


@router.put("/trips/{trip_id}/current-chapter", response=CurrentChapterIn)
def set_current_chapter(request, trip_id: int, payload: CurrentChapterIn):
    """The chapter new posts go into (same as WhatsApp's #chapter). null clears it."""
    trip = get_trip(request.user, trip_id)
    chapter_service.set_current_chapter(request.user, trip, _chapter(trip, payload.chapter_id))
    return {"chapter_id": trip.current_chapter_id}


# Tracks ----------------------------------------------------------------------------

@router.post("/trips/{trip_id}/tracks", response={201: TrackOut})
def create_track(request, trip_id: int, file: File[UploadedFile], name: Form[str] = "",
                 mode: Form[str] = "other", chapter_id: Form[int | None] = None):
    """Upload a GPX file (multipart). It's stored verbatim."""
    trip = get_trip(request.user, trip_id)
    if file.size > settings.GPX_MAX_BYTES:
        raise ApiError(413, "GPX files are limited to 50 MB.")
    if mode not in dict(Track.MODES):
        raise Invalid({"mode": [f"One of: {', '.join(dict(Track.MODES))}."]})
    track = track_service.create_track(request.user, trip, gpx_text=file.read(), name=name[:200], mode=mode,
                                       chapter=_chapter(trip, chapter_id))
    return 201, {"id": track.pk, "name": track.name, "mode": track.mode, "chapter_id": track.chapter_id}
