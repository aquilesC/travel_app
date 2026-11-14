"""Shared response shapes and serialisers."""

from datetime import date, datetime

from django.urls import reverse
from django.utils import timezone
from ninja import Schema

from trips.templatetags.trips_tags import render_markdown


class ErrorBody(Schema):
    code: str
    message: str
    fields: dict[str, list[str]] | None = None
    received: int | None = None


class ErrorOut(Schema):
    """Every API error has this shape (api/errors.py)."""
    error: ErrorBody


class PersonOut(Schema):
    id: int
    name: str


class ChapterOut(Schema):
    id: int
    title: str
    position: int


class TripOut(Schema):
    id: int
    title: str
    start_date: date
    end_date: date
    timezone: str
    description: str
    current: bool
    cover_url: str | None
    updated_at: datetime


class TripDetailOut(TripOut):
    description_html: str
    travellers: list[PersonOut]
    companions: list[str]
    chapters: list[ChapterOut]
    current_chapter_id: int | None
    share_enabled: bool
    share_url: str | None
    live_share: str
    live_delay_minutes: int
    live_round_m: int


class MediaOut(Schema):
    id: int
    kind: str
    status: str
    original_name: str
    is_travel_copy: bool
    sha256: str
    size_bytes: int
    width: int | None
    height: int | None
    duration_seconds: float | None
    taken_at: datetime | None
    latitude: float | None
    longitude: float | None
    position: int
    urls: dict[str, str]


class EntryOut(Schema):
    id: int
    trip_id: int
    chapter_id: int | None
    author: PersonOut
    occurred_at: datetime
    body: str
    body_html: str
    place_name: str
    latitude: float | None
    longitude: float | None
    is_public: bool
    source: str
    media: list[MediaOut]
    created_at: datetime
    updated_at: datetime


def person(user):
    return {"id": user.pk, "name": user.get_full_name() or user.username}


def _float(value):
    return None if value is None else float(value)


def media_url(media, variant):
    return reverse("api-v1:media_file", kwargs={"media_id": media.pk, "variant": variant})


def media_out(media):
    variants = sorted(media.VARIANTS[media.kind])
    return {
        "id": media.pk, "kind": media.kind, "status": media.status, "original_name": media.original_name,
        "is_travel_copy": media.is_travel_copy, "sha256": media.sha256, "size_bytes": media.size_bytes,
        "width": media.width, "height": media.height, "duration_seconds": media.duration_seconds,
        "taken_at": media.taken_at, "latitude": _float(media.latitude), "longitude": _float(media.longitude),
        "position": media.position,
        "urls": {v: media_url(media, v) for v in variants if media.variant_path(v)},
    }


def entry_out(entry):
    return {
        "id": entry.pk, "trip_id": entry.trip_id, "chapter_id": entry.chapter_id,
        "author": person(entry.author), "occurred_at": entry.occurred_at, "body": entry.body,
        "body_html": render_markdown(entry.body), "place_name": entry.place_name,
        "latitude": _float(entry.latitude), "longitude": _float(entry.longitude),
        "is_public": entry.is_public, "source": entry.source,
        "media": [media_out(m) for m in entry.media.all()],
        "created_at": entry.created_at, "updated_at": entry.updated_at,
    }


def is_current(trip):
    return trip.start_date <= timezone.localdate(timezone=trip.tz) <= trip.end_date


def trip_out(trip):
    cover = None
    if trip.cover_id and trip.cover.variant_path("md"):
        cover = media_url(trip.cover, "md")
    return {
        "id": trip.pk, "title": trip.title, "start_date": trip.start_date, "end_date": trip.end_date,
        "timezone": trip.timezone, "description": trip.description, "current": is_current(trip),
        "cover_url": cover, "updated_at": trip.updated_at,
    }


def trip_detail_out(trip):
    return {
        **trip_out(trip),
        "description_html": render_markdown(trip.description),
        "travellers": [person(u) for u in trip.travellers.order_by("first_name", "username")],
        "companions": [p.name for p in trip.companions.all()],
        "chapters": [{"id": c.pk, "title": c.title, "position": c.position} for c in trip.chapters.all()],
        "current_chapter_id": trip.current_chapter_id,
        "share_enabled": trip.share_enabled,
        "share_url": trip.share_url() if trip.share_enabled else None,
        "live_share": trip.live_share, "live_delay_minutes": trip.live_delay_minutes,
        "live_round_m": trip.live_round_m,
    }

