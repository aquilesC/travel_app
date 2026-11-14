"""Where the travellers are now (v4 #27).

Members see exact, up-to-date positions. Share-link viewers (only when the trip allows it)
see them delayed and snapped to a grid. Positions inside a user's privacy zones are never
shown to anyone, on any map.
"""

import math
from datetime import timedelta

from django.utils import timezone

from ..models import Trip
from ..stats import haversine_km

STALE_AFTER = timedelta(hours=24)  # nobody is shown when their last point is older
METRES_PER_DEGREE = 111_320


def zones_for(user):
    return [(float(z.latitude), float(z.longitude), z.radius_m / 1000) for z in user.privacy_zones.all()]


def in_zone(zones, lat, lon):
    return any(haversine_km((zlat, zlon), (lat, lon)) <= radius for zlat, zlon, radius in zones)


def without_zones(user, rows, zones=None):
    """rows: [(utc, lat, lon), ...] minus everything inside the user's privacy zones."""
    zones = zones_for(user) if zones is None else zones
    return [r for r in rows if not in_zone(zones, r[1], r[2])] if zones else rows


def snap(lat, lon, metres):
    if not metres:
        return lat, lon
    lat_step = metres / METRES_PER_DEGREE
    lat = round(round(lat / lat_step) * lat_step, 6)
    # The longitude grid depends on the snapped latitude, so snapping twice changes nothing.
    lon_step = metres / (METRES_PER_DEGREE * max(math.cos(math.radians(lat)), 0.01))
    return lat, round(round(lon / lon_step) * lon_step, 6)


def live_view(trip, *, for_link):
    """{"as_of", "travellers": [{user_id, name, latest: {recorded_at, latitude, longitude}, path}]}.

    `path` is today's track (trip time zone) as [[lon, lat], ...].
    """
    now = timezone.now()
    as_of = now - timedelta(minutes=trip.live_delay_minutes) if for_link else now
    day_start = timezone.localtime(as_of, trip.tz).replace(hour=0, minute=0, second=0, microsecond=0)
    travellers = []
    if trip.live_share == Trip.LIVE_OFF or (for_link and trip.live_share != Trip.LIVE_LINK):
        return {"as_of": as_of, "travellers": travellers}

    for user in trip.travellers.prefetch_related("privacy_zones").order_by("first_name", "username"):
        qs = trip.positions.filter(user=user, recorded_at__lte=as_of,
                                   recorded_at__gte=min(day_start, as_of - STALE_AFTER))
        rows = [(t, float(lat), float(lon)) for t, lat, lon in
                qs.order_by("recorded_at").values_list("recorded_at", "latitude", "longitude")]
        rows = without_zones(user, rows)
        if not rows or as_of - rows[-1][0] > STALE_AFTER:
            continue
        rounding = trip.live_round_m if for_link else 0
        path = []
        for t, lat, lon in rows:
            if t < day_start:
                continue
            point = list(reversed(snap(lat, lon, rounding)))
            if not path or path[-1] != point:
                path.append(point)
        last_t, last_lat, last_lon = rows[-1]
        last_lat, last_lon = snap(last_lat, last_lon, rounding)
        travellers.append({
            "user_id": user.pk, "name": user.get_full_name() or user.username,
            "latest": {"recorded_at": last_t, "latitude": last_lat, "longitude": last_lon},
            "path": path,
        })
    return {"as_of": as_of, "travellers": travellers}
