"""Distances and counts for the public profile."""

import math

from .gpx import GPXError, track_summary

EARTH_RADIUS_KM = 6371.0088


def haversine_km(a, b):
    """Great-circle distance between two (lat, lon) points in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def checkin_points(trip):
    """(lat, lon) of every located entry in time order; photo GPS as fallback."""
    points = []
    for entry in trip.entries.prefetch_related("media").order_by("occurred_at", "id"):
        if entry.has_location:
            points.append((float(entry.latitude), float(entry.longitude)))
            continue
        for media in entry.media.all():
            if media.latitude is not None:
                points.append((float(media.latitude), float(media.longitude)))
                break
    return points


def trip_km(trip):
    """GPX distance when the trip has tracks, else straight lines between check-ins."""
    tracks = list(trip.tracks.all())
    if tracks:
        total = 0.0
        for track in tracks:
            try:
                total += track_summary(track)["stats"]["distance_km"]
            except GPXError:
                pass
        return total
    points = checkin_points(trip)
    return sum(haversine_km(a, b) for a, b in zip(points, points[1:]))


def user_stats(user):
    trips = list(user.travelled_trips.select_related("cover__entry").order_by("-start_date"))
    return {
        "trip_count": len(trips),
        "km": round(sum(trip_km(trip) for trip in trips)),
        "shared_trips": [trip for trip in trips if trip.share_enabled],
    }
