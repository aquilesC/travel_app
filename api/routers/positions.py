from datetime import date, datetime

from django.http import HttpResponse
from ninja import Field, Router, Schema

from trips.access import get_trip
from trips.services import positions as service
from trips.services.errors import NotFound

router = Router(tags=["positions"])


class PointIn(Schema):
    recorded_at: datetime = Field(description="When the phone recorded it; must include a UTC offset.")
    latitude: float
    longitude: float
    accuracy_m: float | None = None
    altitude_m: float | None = None
    speed_mps: float | None = None


class BatchIn(Schema):
    points: list[PointIn] = Field(max_length=service.MAX_BATCH)


class Rejected(Schema):
    index: int
    reason: str


class BatchOut(Schema):
    accepted: int
    duplicates: int
    rejected: list[Rejected]


class PointOut(Schema):
    recorded_at: datetime
    latitude: float
    longitude: float
    accuracy_m: float | None
    user_id: int


class PointsOut(Schema):
    items: list[PointOut]
    next_cursor: str | None


@router.post("/trips/{trip_id}/positions", response=BatchOut)
def add_positions(request, trip_id: int, payload: BatchIn):
    """Store a batch of recorded points for the caller. Safe to retry: duplicates are ignored."""
    trip = get_trip(request.user, trip_id)
    return service.record_positions(request.user, trip, [p.dict() for p in payload.points])


def _member(trip, user_id):
    if user_id is None:
        return None
    user = trip.travellers.filter(pk=user_id).first()
    if user is None:
        raise NotFound("That person isn't on this trip.")
    return user


@router.get("/trips/{trip_id}/positions", response=PointsOut)
def list_positions(request, trip_id: int, user: int | None = None, cursor: str | None = None,
                   limit: int = 1000):
    """Recorded points in time order. `cursor` is the `recorded_at` of the last point you have."""
    trip = get_trip(request.user, trip_id)
    since = datetime.fromisoformat(cursor) if cursor else None
    limit = max(1, min(limit, service.MAX_BATCH))
    rows = list(service.positions(request.user, trip, user=_member(trip, user), since=since)[:limit + 1])
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [{"recorded_at": p.recorded_at, "latitude": float(p.latitude),
                   "longitude": float(p.longitude), "accuracy_m": p.accuracy_m, "user_id": p.user_id}
                  for p in rows],
        "next_cursor": rows[-1].recorded_at.isoformat() if more else None,
    }


@router.get("/trips/{trip_id}/positions.gpx", response={200: str}, url_name="positions_gpx")
def positions_gpx(request, trip_id: int, user: int | None = None, day: date | None = None):
    """GPX export of one traveller's recorded positions (default: you), whole trip or one local day."""
    trip = get_trip(request.user, trip_id)
    who = _member(trip, user) or request.user
    text = service.gpx_export(request.user, trip, who, day)
    name = f"trip-{trip.pk}-{who.username}{'-' + day.isoformat() if day else ''}.gpx"
    response = HttpResponse(text, content_type="application/gpx+xml")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response
