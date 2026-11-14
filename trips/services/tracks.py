from django.conf import settings

from ..access import ensure_member
from ..gpx import GPXError, parse_gpx
from ..models import Track
from ._util import validated
from .errors import Invalid

TRACK_FIELDS = ("name", "mode", "chapter")


def read_gpx(raw, field="gpx_file"):
    """bytes/str of an uploaded GPX file → validated text. Raises Invalid."""
    if isinstance(raw, bytes):
        if len(raw) > settings.GPX_MAX_BYTES:
            raise Invalid({field: ["GPX files are limited to 50 MB."]})
        try:
            raw = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise Invalid({field: ["The file is not UTF-8 text."]}) from None
    try:
        parse_gpx(raw)
    except GPXError as exc:
        raise Invalid({field: [f"Not a readable GPX file: {exc}"]}) from None
    return raw


def _check_chapter(trip, chapter):
    if chapter is not None and chapter.trip_id != trip.pk:
        raise Invalid({"chapter": ["That chapter belongs to another trip."]})


def create_track(actor, trip, *, gpx_text, **fields):
    ensure_member(actor, trip)
    _check_chapter(trip, fields.get("chapter"))
    track = Track(trip=trip, uploaded_by=actor, gpx_text=read_gpx(gpx_text),
                  **{k: v for k, v in fields.items() if k in TRACK_FIELDS})
    validated(track)
    track.save()
    return track


def update_track(actor, track, *, gpx_text=None, **fields):
    ensure_member(actor, track.trip)
    _check_chapter(track.trip, fields.get("chapter"))
    for key, value in fields.items():
        if key in TRACK_FIELDS:
            setattr(track, key, value)
    if gpx_text is not None:
        track.gpx_text = read_gpx(gpx_text)
    validated(track)
    track.save()
    return track


def delete_track(actor, track):
    ensure_member(actor, track.trip)
    track.delete()
