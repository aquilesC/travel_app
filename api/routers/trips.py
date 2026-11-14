from datetime import datetime

from django.db.models import Prefetch, Q
from django.http import HttpResponseRedirect
from django.urls import reverse
from ninja import Router, Schema

from trips.access import get_owned, get_trip, member_trips
from trips.gpx import map_data
from trips.media import file_response
from trips.models import Entry, Media, Tombstone, Trip
from trips.services.errors import NotFound

from .. import pagination
from ..schemas import EntryOut, TripDetailOut, TripOut, entry_out, media_url, trip_detail_out, trip_out

router = Router(tags=["trips"])


class TripList(Schema):
    items: list[TripOut]
    next_cursor: str | None = None


class EntryPage(Schema):
    items: list[EntryOut]
    next_cursor: str | None
    deleted: list[int] = []


def entries_qs():
    return Entry.objects.select_related("author").prefetch_related(
        Prefetch("media", queryset=Media.objects.order_by("position", "id")))


@router.get("/trips", response=TripList)
def list_trips(request):
    """Trips you're a member of, newest first. `current` marks trips happening today."""
    return {"items": [trip_out(t) for t in member_trips(request.user).select_related("cover")]}


@router.get("/trips/{trip_id}", response=TripDetailOut)
def trip_detail(request, trip_id: int):
    trip = get_trip(request.user, trip_id, Trip.objects.select_related("cover").prefetch_related(
        "chapters", "companions", "travellers"))
    return trip_detail_out(trip)


@router.get("/trips/{trip_id}/entries", response=EntryPage)
def list_entries(request, trip_id: int, updated_since: datetime | None = None,
                 cursor: str | None = None, limit: int = 50):
    """Entries ordered by last change (oldest first), for incremental sync.

    With `updated_since`, only entries changed after it, plus `deleted`: ids of entries
    deleted after it.
    """
    trip = get_trip(request.user, trip_id)
    limit = pagination.clamp(limit)
    qs = entries_qs().filter(trip=trip).order_by("updated_at", "id")
    if updated_since:
        qs = qs.filter(updated_at__gt=updated_since)
    if cursor:
        when, pk = pagination.decode(cursor)
        qs = qs.filter(Q(updated_at__gt=when) | Q(updated_at=when, id__gt=pk))
    rows = list(qs[:limit + 1])
    page = rows[:limit]
    deleted = []
    if updated_since and not cursor:
        deleted = list(Tombstone.objects.filter(trip_id=trip.pk, model="entry", deleted_at__gt=updated_since)
                       .values_list("object_id", flat=True))
    return {
        "items": [entry_out(e) for e in page],
        "next_cursor": pagination.encode(page[-1].updated_at, page[-1].pk) if len(rows) > limit else None,
        "deleted": deleted,
    }


@router.get("/entries/{entry_id}", response=EntryOut, url_name="entry_detail")
def entry_detail(request, entry_id: int):
    return entry_out(get_owned(request.user, entries_qs(), pk=entry_id))


@router.get("/trips/{trip_id}/map", url_name="trip_map")
def trip_map(request, trip_id: int):
    """GeoJSON FeatureCollection: GPX tracks, recorded paths, check-ins, the path between them, photos."""
    trip = get_trip(request.user, trip_id)
    return map_data(trip, public_only=False, media_url=media_url)


@router.get("/share/{token}/map", auth=None, url_name="share_map")
def share_map(request, token: str):
    """The share page's map: public entries and their photos only, no recorded positions."""
    trip = Trip.objects.filter(share_token=token, share_enabled=True).first()
    if trip is None:
        raise NotFound("Not found.")
    return map_data(trip, public_only=True,
                    media_url=lambda m, v: reverse("share_media", args=[token, m.pk, v]))


@router.get("/media/{media_id}/{variant}", url_name="media_file")
def media_file(request, media_id: int, variant: str):
    """The file itself (original or a processed variant), served by nginx after this check."""
    media = get_owned(request.user, Media, pk=media_id)
    return file_response(media.variant_path(variant))
