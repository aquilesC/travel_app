from datetime import datetime

from django.core.cache import cache
from ninja import Router, Schema

from trips.access import get_trip
from trips.models import Trip
from trips.services.errors import NotFound
from trips.services.live import live_view

router = Router(tags=["live"])
SHARE_CACHE_SECONDS = 30


class LatestOut(Schema):
    recorded_at: datetime
    latitude: float
    longitude: float


class TravellerOut(Schema):
    user_id: int
    name: str
    latest: LatestOut
    path: list[list[float]]


class LiveOut(Schema):
    as_of: datetime
    delay_minutes: int
    rounding_m: int
    travellers: list[TravellerOut]


@router.get("/trips/{trip_id}/live", response=LiveOut, url_name="trip_live")
def trip_live(request, trip_id: int):
    """Members: exact latest position and today's path per traveller (privacy zones removed)."""
    trip = get_trip(request.user, trip_id)
    return {**live_view(trip, for_link=False), "delay_minutes": 0, "rounding_m": 0}


@router.get("/share/{token}/live", response=LiveOut, auth=None, url_name="share_live")
def share_live(request, token: str):
    """Share-link viewers, only when the trip shares live location with the link: delayed and rounded."""
    trip = Trip.objects.filter(share_token=token, share_enabled=True).first()
    if trip is None or trip.live_share != Trip.LIVE_LINK:
        raise NotFound("Not found.")
    key = f"share-live:{trip.pk}:{trip.updated_at.timestamp()}"
    data = cache.get(key)
    if data is None:
        data = {**live_view(trip, for_link=True), "delay_minutes": trip.live_delay_minutes,
                "rounding_m": trip.live_round_m}
        cache.set(key, data, SHARE_CACHE_SECONDS)
    return data
