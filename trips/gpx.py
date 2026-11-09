"""GPX parsing at render time. Track.gpx_text stays the source of truth; the
simplified GeoJSON is only cached (keyed on the track's updated_at)."""

import gpxpy
import gpxpy.gpx
from django.core.cache import cache

SIMPLIFY_METRES = 10
MODE_COLORS = {
    "sail": "#1f6feb", "bike": "#d97706", "hike": "#15803d", "walk": "#65a30d",
    "car": "#7c3aed", "transit": "#db2777", "other": "#475569",
}


class GPXError(ValueError):
    pass


def parse_gpx(text):
    try:
        gpx = gpxpy.parse(text)
    except (gpxpy.gpx.GPXException, ValueError) as exc:
        raise GPXError(str(exc)) from exc
    if not any(seg.points for t in gpx.tracks for seg in t.segments) and not any(
        r.points for r in gpx.routes
    ):
        raise GPXError("no track or route points found")
    return gpx


def _summarise(text):
    gpx = parse_gpx(text)
    distance_km = (gpx.length_2d() or 0) / 1000
    duration = gpx.get_duration() or 0
    uphill, _ = gpx.get_uphill_downhill()
    bounds = gpx.get_time_bounds()
    gpx.simplify(max_distance=SIMPLIFY_METRES)

    lines = [
        [[round(p.longitude, 6), round(p.latitude, 6)] for p in segment.points]
        for track in gpx.tracks for segment in track.segments if len(segment.points) > 1
    ] + [
        [[round(p.longitude, 6), round(p.latitude, 6)] for p in route.points]
        for route in gpx.routes if len(route.points) > 1
    ]
    return {
        "lines": lines,
        "stats": {
            "distance_km": round(distance_km, 2),
            "duration_s": int(duration),
            "uphill_m": round(uphill or 0),
            "start": bounds.start_time.isoformat() if bounds.start_time else None,
            "end": bounds.end_time.isoformat() if bounds.end_time else None,
        },
    }


def track_summary(track):
    key = f"track:{track.pk}:{track.updated_at.timestamp()}"
    summary = cache.get(key)
    if summary is None:
        summary = _summarise(track.gpx_text)
        cache.set(key, summary)
    return summary


def track_feature(track):
    summary = track_summary(track)
    return {
        "type": "Feature",
        "geometry": {"type": "MultiLineString", "coordinates": summary["lines"]},
        "properties": {
            "kind": "track", "name": str(track), "mode": track.mode,
            "mode_label": track.get_mode_display(), "color": MODE_COLORS.get(track.mode, "#475569"),
            **summary["stats"],
        },
    }


def map_data(trip, public_only):
    """GeoJSON for the trip map: tracks, entry check-ins, and the path between them."""
    features = [track_feature(t) for t in trip.tracks.all()]

    entries = trip.entries.prefetch_related("media")
    if public_only:
        entries = entries.filter(is_public=True)
    points = []
    for entry in entries.order_by("occurred_at", "id"):
        located = [(entry.latitude, entry.longitude)] if entry.has_location else [
            (m.latitude, m.longitude) for m in entry.media.all() if m.latitude is not None
        ][:1]
        for lat, lon in located:
            coordinates = [float(lon), float(lat)]
            points.append(coordinates)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coordinates},
                "properties": {
                    "kind": "entry", "entry_id": entry.pk,
                    "title": entry.place_name or entry.body[:60],
                    "anchor": f"#entry-{entry.pk}",
                },
            })
    if len(points) > 1:
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": points},
            "properties": {"kind": "path"},
        })
    return {"type": "FeatureCollection", "features": features}
