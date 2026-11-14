"""Bulk imports: photos (and GPX) into an existing or a new trip.

Pipeline: staged ImportItems (metadata read at upload) → capture times in UTC
(camera shift applied) → missing locations filled from GPX tracks or nearby
photos → grouped into entries → Media rows → processing enqueued.
"""

import bisect
import os
import shutil
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

from django.conf import settings
from django.db import transaction
from PIL import ExifTags, Image, UnidentifiedImageError

from .gpx import parse_gpx
from .services.media import kind_for, sha256_of
from .models import Entry, ImportBatch, ImportItem, Media, Track, Trip
from .processing import probe, probe_metadata
from .stats import haversine_km

GROUP_GAP = timedelta(minutes=60)
GROUP_RADIUS_KM = 2.0
GPX_TOLERANCE = timedelta(minutes=10)
NEIGHBOUR_WINDOW = timedelta(hours=6)
NEIGHBOUR_COPY_WINDOW = timedelta(hours=1)
LEGACY_ZONES = {"Asia/Calcutta", "Asia/Katmandu", "Asia/Saigon", "Asia/Rangoon", "Asia/Dacca",
                "Asia/Thimbu", "Asia/Ulan_Bator", "Atlantic/Faeroe", "Europe/Kiev", "America/Godthab",
                "Pacific/Truk", "Pacific/Ponape", "Pacific/Enderbury", "Asia/Ujung_Pandang"}


# Metadata at upload time ---------------------------------------------------------

def _dms(value, ref):
    degrees, minutes, seconds = (float(v) for v in value)
    result = degrees + minutes / 60 + seconds / 3600
    return Decimal(f"{-result if ref in ('S', 'W') else result:.6f}")


def _offset_minutes(text):
    text = str(text or "").strip("\x00 ")
    if len(text) == 6 and text[0] in "+-" and text[3] == ":":
        sign = -1 if text[0] == "-" else 1
        return sign * (int(text[1:3]) * 60 + int(text[4:6]))
    return None


def read_metadata(path, kind):
    """{taken_local, taken_offset_minutes, camera, latitude, longitude} for an upload."""
    meta = {"taken_local": None, "taken_offset_minutes": None, "camera": "",
            "latitude": None, "longitude": None}
    if kind == Media.PHOTO:
        try:
            with Image.open(path) as image:
                exif = image.getexif()
        except (UnidentifiedImageError, OSError):
            return meta
        details = exif.get_ifd(ExifTags.IFD.Exif)
        stamp = details.get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTime)
        if stamp:
            try:
                naive = datetime.strptime(str(stamp).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
                meta["taken_local"] = naive.replace(tzinfo=dt_timezone.utc)
            except ValueError:
                pass
        meta["taken_offset_minutes"] = _offset_minutes(details.get(ExifTags.Base.OffsetTimeOriginal))
        make = str(exif.get(ExifTags.Base.Make) or "").strip("\x00 ")
        model = str(exif.get(ExifTags.Base.Model) or "").strip("\x00 ")
        meta["camera"] = (model if model.startswith(make) else f"{make} {model}").strip()[:120]
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        if gps.get(2) and gps.get(4):
            try:
                meta["latitude"] = _dms(gps[2], gps.get(1, "N"))
                meta["longitude"] = _dms(gps[4], gps.get(3, "E"))
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    elif kind == Media.VIDEO:
        try:
            info = probe(path)
        except Exception:
            return meta
        _, taken_at, meta["latitude"], meta["longitude"] = probe_metadata(info)
        if taken_at is not None:
            offset = taken_at.utcoffset()
            meta["taken_offset_minutes"] = int(offset.total_seconds() // 60)
            meta["taken_local"] = taken_at.replace(tzinfo=dt_timezone.utc) + offset
        tags = {k.lower(): v for k, v in (info.get("format", {}).get("tags") or {}).items()}
        meta["camera"] = (tags.get("com.apple.quicktime.model") or "")[:120]
    return meta


def stage_file(batch, source_path, filename):
    """Move a finished upload into the batch. Returns (item, None) or (None, reason)."""
    kind = kind_for(filename)
    if kind is None:
        return None, f"Unsupported file type: {filename}"
    digest = sha256_of(source_path)
    if batch.items.filter(sha256=digest).exists():
        return None, f"{filename} is already in this import."
    if batch.trip_id and Media.objects.filter(entry__trip=batch.trip_id, sha256=digest).exists():
        return None, f"{filename} is already in this trip."

    ext = Path(filename).suffix.lower()[:10]
    relative = f"originals/imports/{batch.pk}/{uuid.uuid4().hex}{ext}"
    target = Path(settings.MEDIA_ROOT) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    size = Path(source_path).stat().st_size
    os.replace(source_path, target)
    item = ImportItem.objects.create(
        batch=batch, path=relative, original_name=filename[:255], kind=kind, sha256=digest,
        size_bytes=size, **read_metadata(target, kind),
    )
    return item, None


def discard_batch(batch):
    shutil.rmtree(Path(settings.MEDIA_ROOT) / "originals" / "imports" / str(batch.pk), ignore_errors=True)
    batch.delete()


# Times ---------------------------------------------------------------------------

def parse_shift(text):
    """'+5:30', '-1', '0:45' → minutes. Raises ValueError."""
    text = (text or "").strip()
    if not text:
        return 0
    sign = -1 if text.startswith("-") else 1
    hours, _, minutes = text.lstrip("+-").partition(":")
    return sign * (int(hours or 0) * 60 + int(minutes or 0))


def format_shift(minutes):
    sign = "-" if minutes < 0 else "+"
    return f"{sign}{abs(minutes) // 60}:{abs(minutes) % 60:02d}"


def item_utc(item, tz, shifts):
    if item.taken_local is None:
        return None
    wall = item.taken_local.replace(tzinfo=None) + timedelta(minutes=shifts.get(item.camera, 0))
    if item.taken_offset_minutes is not None:
        aware = wall.replace(tzinfo=dt_timezone(timedelta(minutes=item.taken_offset_minutes)))
    else:  # camera clock assumed to be local trip time
        aware = wall.replace(tzinfo=tz)
    return aware.astimezone(dt_timezone.utc)


def guess_timezone(items):
    """Most common recorded UTC offset → a zone with that offset at that date."""
    offsets = Counter((i.taken_offset_minutes, i.taken_local.date()) for i in items
                      if i.taken_offset_minutes is not None and i.taken_local)
    if not offsets:
        return "Europe/Amsterdam"
    (minutes, day), _ = offsets.most_common(1)[0]
    moment = datetime.combine(day, datetime.min.time()) + timedelta(hours=12)
    target = timedelta(minutes=minutes)
    candidates = sorted(
        z for z in available_timezones()
        if "/" in z and not z.startswith(("Etc/", "SystemV/", "US/")) and z not in LEGACY_ZONES
        and ZoneInfo(z).utcoffset(moment) == target
    )
    if "Europe/Amsterdam" in candidates:
        return "Europe/Amsterdam"
    return candidates[0] if candidates else "UTC"


# Locations ---------------------------------------------------------------------

@dataclass
class Point:
    item: ImportItem
    utc: datetime | None
    lat: float | None = None
    lon: float | None = None
    source: str = ""


def track_series(tracks):
    """One time-sorted [(utc, lat, lon)] list per GPX segment with timestamps."""
    series = []
    for track in tracks:
        try:
            gpx = parse_gpx(track.gpx_text)
        except ValueError:
            continue
        for t in gpx.tracks:
            for segment in t.segments:
                points = sorted(
                    (p.time.astimezone(dt_timezone.utc), p.latitude, p.longitude)
                    for p in segment.points if p.time is not None
                )
                if points:
                    series.append(points)
    return series


def location_series(trip, user=None):
    """Everything that can place a photo without GPS: the trip's GPX tracks, then the
    importing user's recorded positions (v4 #26)."""
    series = track_series(trip.tracks.all())
    if user is not None:
        from .services.positions import series_for

        series += series_for(trip, user)
    return series


def gpx_position(series, when):
    for points in series:
        if not (points[0][0] - GPX_TOLERANCE <= when <= points[-1][0] + GPX_TOLERANCE):
            continue
        if when <= points[0][0]:
            return points[0][1:]
        if when >= points[-1][0]:
            return points[-1][1:]
        index = bisect.bisect_left(points, (when,))
        (t0, lat0, lon0), (t1, lat1, lon1) = points[index - 1], points[index]
        f = (when - t0) / (t1 - t0) if t1 != t0 else 0
        return lat0 + (lat1 - lat0) * f, lon0 + (lon1 - lon0) * f
    return None


def fill_locations(points, series):
    """Points without GPS: GPX first, then nearby located photos. Mutates points."""
    located = [p for p in points if p.lat is not None and p.utc is not None]
    times = [p.utc for p in located]
    for p in points:
        if p.lat is not None or p.utc is None:
            continue
        position = gpx_position(series, p.utc)
        if position:
            p.lat, p.lon, p.source = position[0], position[1], "gpx"
            continue
        index = bisect.bisect_left(times, p.utc)
        before = located[index - 1] if index > 0 else None
        after = located[index] if index < len(located) else None
        near_before = before and p.utc - before.utc <= NEIGHBOUR_WINDOW
        near_after = after and after.utc - p.utc <= NEIGHBOUR_WINDOW
        if near_before and near_after:
            span = (after.utc - before.utc).total_seconds()
            f = (p.utc - before.utc).total_seconds() / span if span else 0
            p.lat = before.lat + (after.lat - before.lat) * f
            p.lon = before.lon + (after.lon - before.lon) * f
            p.source = "interpolated"
        else:
            for neighbour, close in ((before, before and p.utc - before.utc <= NEIGHBOUR_COPY_WINDOW),
                                     (after, after and after.utc - p.utc <= NEIGHBOUR_COPY_WINDOW)):
                if close:
                    p.lat, p.lon, p.source = neighbour.lat, neighbour.lon, "interpolated"
                    break


def group_points(points):
    """Split time-sorted points into entries by time gap and distance."""
    groups = []
    anchor = None
    for p in points:
        start_new = not groups
        if groups:
            previous = groups[-1][-1]
            if p.utc and previous.utc and p.utc - previous.utc > GROUP_GAP:
                start_new = True
            elif anchor and p.lat is not None and haversine_km(anchor, (p.lat, p.lon)) > GROUP_RADIUS_KM:
                start_new = True
        if start_new:
            groups.append([])
            anchor = None
        groups[-1].append(p)
        if anchor is None and p.lat is not None:
            anchor = (p.lat, p.lon)
    return groups


def build_points(items, tz, shifts, series):
    points = []
    for item in items:
        p = Point(item=item, utc=item_utc(item, tz, shifts))
        if item.latitude is not None:
            p.lat, p.lon, p.source = float(item.latitude), float(item.longitude), "exif"
        points.append(p)
    dated = sorted((p for p in points if p.utc), key=lambda p: (p.utc, p.item.pk))
    undated = [p for p in points if p.utc is None]
    fill_locations(dated, series)
    return dated, undated


def date_range(items, tz, shifts):
    times = [t for t in (item_utc(i, tz, shifts) for i in items) if t]
    if not times:
        return None, None
    return min(times).astimezone(tz).date(), max(times).astimezone(tz).date()


# Creating entries ------------------------------------------------------------------

def _decimal(value):
    return None if value is None else Decimal(f"{value:.6f}")


@transaction.atomic
def create_entries(batch, trip, shifts, make_public, author):
    from .tasks import process_media

    items = list(batch.items.all())
    dated, undated = build_points(items, trip.tz, shifts, location_series(trip, author))
    groups = group_points(dated)
    if undated:
        groups.append(undated)
    fallback_time = datetime.combine(trip.start_date, datetime.min.time(), tzinfo=trip.tz) + timedelta(hours=12)

    entries = []
    for group in groups:
        first_located = next((p for p in group if p.lat is not None), None)
        entry = Entry.objects.create(
            trip=trip, author=author, occurred_at=group[0].utc or fallback_time,
            latitude=_decimal(first_located.lat) if first_located else None,
            longitude=_decimal(first_located.lon) if first_located else None,
            is_public=make_public, source=Entry.SOURCE_WEB,
        )
        for position, p in enumerate(group):
            item = p.item
            media = Media(
                entry=entry, kind=item.kind, original_name=item.original_name, sha256=item.sha256,
                size_bytes=item.size_bytes, position=position, taken_at=p.utc,
                latitude=_decimal(p.lat), longitude=_decimal(p.lon), location_source=p.source,
            )
            media.original.name = item.path
            media.save()
            process_media.enqueue(media.pk)  # DB backend: visible to the worker on commit
        entries.append(entry)

    batch.items.all().delete()  # files now belong to the Media rows
    batch.trip = trip
    batch.status = ImportBatch.DONE
    batch.entry_ids = [e.pk for e in entries]
    batch.save(update_fields=["trip", "status", "entry_ids"])
    return entries


@transaction.atomic
def create_trip_from_batch(batch, *, title, tz_name, travellers, gpx_texts, shifts, make_public, author):
    tz = ZoneInfo(tz_name)
    items = list(batch.items.all())
    start, end = date_range(items, tz, shifts)
    if start is None:
        start = end = date.today()
    trip = Trip.objects.create(title=title or f"Trip {start:%B %Y}", start_date=start, end_date=end,
                               timezone=tz_name, created_by=author)
    trip.travellers.set({*travellers, author})  # creator is always a member
    for name, text in gpx_texts:
        Track.objects.create(trip=trip, name=name, gpx_text=text, uploaded_by=author)
    create_entries(batch, trip, shifts, make_public, author)
    return trip


# Trip from GPX (#12) ---------------------------------------------------------------

def gpx_name(text, filename):
    gpx = parse_gpx(text)
    for candidate in [*(t.name for t in gpx.tracks), gpx.name]:
        if candidate:
            return candidate.strip()[:200]
    return Path(filename).stem[:200]


@transaction.atomic
def create_trip_from_gpx(*, files, tz_name, mode, title, start_date, end_date, travellers, author):
    """files: [(filename, text)], already validated. Returns the trip."""
    tz = ZoneInfo(tz_name)
    bounds = []
    for _, text in files:
        times = parse_gpx(text).get_time_bounds()
        if times.start_time and times.end_time:
            bounds += [times.start_time, times.end_time]
    if bounds:
        start_date = min(bounds).astimezone(tz).date()
        end_date = max(bounds).astimezone(tz).date()
    names = [gpx_name(text, filename) for filename, text in files]
    trip = Trip.objects.create(
        title=title or names[0] or f"Trip {start_date:%B %Y}", start_date=start_date,
        end_date=end_date, timezone=tz_name, created_by=author,
    )
    trip.travellers.set({*travellers, author})  # creator is always a member
    for (_, text), name in zip(files, names):
        Track.objects.create(trip=trip, name=name, mode=mode, gpx_text=text, uploaded_by=author)
    return trip


def has_timestamps(text):
    bounds = parse_gpx(text).get_time_bounds()
    return bool(bounds.start_time and bounds.end_time)
