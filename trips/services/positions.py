"""Positions recorded by the app: batch ingest, paths for the map, GPX export (v4 #26)."""

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import gpxpy.gpx
from django.core.cache import cache
from django.db.models import Count, Max

from ..access import ensure_member
from ..models import Position
from ..stats import haversine_km

MAX_BATCH = 5000
MAX_ACCURACY_M = 500
PATH_GAP = timedelta(minutes=30)  # a longer silence breaks the line
SIMPLIFY_KM = 0.010


def _day_bounds(trip, day):
    start = datetime.combine(day, datetime.min.time(), tzinfo=trip.tz)
    return start, start + timedelta(days=1)


def _reject_reason(trip, point, earliest, latest):
    when = point["recorded_at"]
    if when.tzinfo is None:
        return "recorded_at needs a time zone (use UTC)."
    if not (earliest <= when < latest):
        return "Outside the trip's dates."
    if not (-90 <= point["latitude"] <= 90 and -180 <= point["longitude"] <= 180):
        return "Coordinates out of range."
    accuracy = point.get("accuracy_m")
    if accuracy is not None and (accuracy < 0 or accuracy > MAX_ACCURACY_M):
        return f"Accuracy worse than {MAX_ACCURACY_M} m."
    return None


def record_positions(actor, trip, points):
    """points: [{recorded_at, latitude, longitude, accuracy_m?, altitude_m?, speed_mps?}].

    Points are checked one by one: bad ones are reported, the rest stored. A point the
    user already sent (same recorded_at) is a duplicate, so retried batches are harmless.
    Returns {"accepted", "duplicates", "rejected": [{"index", "reason"}]}.
    """
    ensure_member(actor, trip)
    earliest = _day_bounds(trip, trip.start_date - timedelta(days=1))[0]
    latest = _day_bounds(trip, trip.end_date + timedelta(days=1))[1]

    rejected, valid = [], {}
    for index, point in enumerate(points[:MAX_BATCH]):
        reason = _reject_reason(trip, point, earliest, latest)
        if reason:
            rejected.append({"index": index, "reason": reason})
        else:
            valid.setdefault(point["recorded_at"].astimezone(dt_timezone.utc), point)
    for index in range(MAX_BATCH, len(points)):
        rejected.append({"index": index, "reason": f"More than {MAX_BATCH} points in one request."})

    existing = set()
    if valid:
        existing = set(Position.objects.filter(
            user=actor, recorded_at__gte=min(valid), recorded_at__lte=max(valid),
        ).values_list("recorded_at", flat=True))
    new = [
        Position(trip=trip, user=actor, recorded_at=when,
                 latitude=Decimal(f"{p['latitude']:.6f}"), longitude=Decimal(f"{p['longitude']:.6f}"),
                 accuracy_m=p.get("accuracy_m"), altitude_m=p.get("altitude_m"),
                 speed_mps=p.get("speed_mps"))
        for when, p in valid.items() if when not in existing
    ]
    Position.objects.bulk_create(new, ignore_conflicts=True)  # a concurrent retry can't fail us
    considered = len(points[:MAX_BATCH]) - sum(1 for r in rejected if r["index"] < MAX_BATCH)
    return {"accepted": len(new), "duplicates": considered - len(new), "rejected": rejected}


def positions(actor, trip, *, user=None, since=None, until=None):
    ensure_member(actor, trip)
    qs = trip.positions.all()
    if user is not None:
        qs = qs.filter(user=user)
    if since is not None:
        qs = qs.filter(recorded_at__gt=since)
    if until is not None:
        qs = qs.filter(recorded_at__lt=until)
    return qs.order_by("recorded_at", "id")


# Geometry ------------------------------------------------------------------------

def segments(rows, gap=PATH_GAP):
    """[(utc, lat, lon), ...] sorted → list of segments split where the gap is too long."""
    result = []
    for row in rows:
        if not result or row[0] - result[-1][-1][0] > gap:
            result.append([])
        result[-1].append(row)
    return result


def simplify(segment, min_km=SIMPLIFY_KM):
    """Drop points closer than min_km to the last kept one (always keeps the ends)."""
    if len(segment) < 3:
        return segment
    kept = [segment[0]]
    for row in segment[1:-1]:
        if haversine_km(kept[-1][1:], row[1:]) >= min_km:
            kept.append(row)
    kept.append(segment[-1])
    return kept


def _rows(qs):
    return [(t, float(lat), float(lon))
            for t, lat, lon in qs.values_list("recorded_at", "latitude", "longitude")]


def series_for(trip, user):
    """Time-sorted segments in the shape importing.fill_locations reads from GPX tracks."""
    return segments(_rows(trip.positions.filter(user=user).order_by("recorded_at")))


def km(segs):
    return sum(haversine_km(a[1:], b[1:]) for seg in segs for a, b in zip(seg, seg[1:]))


def path_features(trip):
    """One MultiLineString per traveller who recorded positions (members' map only).

    Points inside the traveller's privacy zones are left out (v4 #27). Cached per user
    until a new point arrives or their zones change.
    """
    from .live import without_zones, zones_for

    features = []
    stats = (trip.positions.values("user").annotate(n=Count("id"), last=Max("received_at"))
             .order_by("user"))
    users = {u.pk: u for u in trip.travellers.prefetch_related("privacy_zones")}
    for row in stats:
        user = users.get(row["user"])
        if user is None:
            continue
        zones = zones_for(user)
        key = f"positions:{trip.pk}:{user.pk}:{row['n']}:{row['last'].timestamp()}:{hash(tuple(zones))}"
        lines = cache.get(key)
        if lines is None:
            rows = without_zones(user, _rows(trip.positions.filter(user=user).order_by("recorded_at")), zones)
            segs = segments(rows)
            lines = {"coords": [[[round(lon, 6), round(lat, 6)] for _, lat, lon in simplify(s)]
                                for s in segs if len(s) > 1],
                     "km": round(km(segs), 2)}
            cache.set(key, lines)
        if lines["coords"]:
            features.append({
                "type": "Feature",
                "geometry": {"type": "MultiLineString", "coordinates": lines["coords"]},
                "properties": {"kind": "recorded", "user_id": user.pk,
                               "name": user.get_full_name() or user.username, "distance_km": lines["km"]},
            })
    return features


def day_km(trip, user, day):
    start, end = _day_bounds(trip, day)
    rows = _rows(trip.positions.filter(user=user, recorded_at__gte=start, recorded_at__lt=end)
                 .order_by("recorded_at"))
    return km(segments(rows))


def gpx_export(actor, trip, user, day=None):
    """GPX text of a user's recorded positions, for the whole trip or one local day."""
    qs = positions(actor, trip, user=user)
    if day is not None:
        start, end = _day_bounds(trip, day)
        qs = qs.filter(recorded_at__gte=start, recorded_at__lt=end)
    gpx = gpxpy.gpx.GPX()
    gpx.creator = "trips.aquiles.me"
    track = gpxpy.gpx.GPXTrack(name=f"{trip.title} – {user.get_full_name() or user.username}"
                                    + (f" – {day:%Y-%m-%d}" if day else ""))
    gpx.tracks.append(track)
    rows = list(qs.values_list("recorded_at", "latitude", "longitude", "altitude_m"))
    for seg in segments([(t, lat, lon, ele) for t, lat, lon, ele in rows]):
        segment = gpxpy.gpx.GPXTrackSegment()
        segment.points = [gpxpy.gpx.GPXTrackPoint(float(lat), float(lon), elevation=ele, time=t)
                          for t, lat, lon, ele in seg]
        track.segments.append(segment)
    return gpx.to_xml(version="1.1")
