"""Derivative generation for uploaded media. Originals are never modified."""

import json
import logging
import re
import subprocess
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from PIL import ExifTags, Image, ImageOps
from pillow_heif import register_heif_opener

from .models import Media

register_heif_opener()
log = logging.getLogger(__name__)

PHOTO_SIZES = {"sm": 400, "md": 1200, "lg": 2400}
VIDEO_SHORT_SIDE = 720
BROWSER_AUDIO = {".mp3", ".m4a", ".aac"}


def media_path(relative):
    return Path(settings.MEDIA_ROOT) / relative


def derived_name(media, suffix):
    return f"derived/{media.entry.trip_id}/{media.pk}_{suffix}"


def process(media_id):
    media = Media.objects.select_related("entry__trip").get(pk=media_id)
    handler = {Media.PHOTO: process_photo, Media.VIDEO: process_video, Media.AUDIO: process_audio}
    try:
        handler[media.kind](media)
        media.status, media.error = Media.READY, ""
    except Exception as exc:  # recorded on the row; "retry" button re-runs it
        log.exception("Processing media %s failed", media_id)
        media.status, media.error = Media.FAILED, f"{type(exc).__name__}: {exc}"[:2000]
    media.save()


# Photos ----------------------------------------------------------------------

def _ratio(value):
    return float(value[0]) / float(value[1]) if isinstance(value, tuple) else float(value)


def _gps_coordinate(dms, ref):
    degrees, minutes, seconds = (_ratio(v) for v in dms)
    value = degrees + minutes / 60 + seconds / 3600
    if ref in ("S", "W"):
        value = -value
    return Decimal(f"{value:.6f}")


def exif_metadata(exif, default_tz):
    """(taken_at, latitude, longitude) from Pillow EXIF; each may be None."""
    taken_at = latitude = longitude = None
    details = exif.get_ifd(ExifTags.IFD.Exif)
    stamp = details.get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTime)
    if stamp:
        try:
            naive = datetime.strptime(str(stamp).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
            offset = details.get(ExifTags.Base.OffsetTimeOriginal)
            if offset:
                taken_at = datetime.fromisoformat(naive.isoformat() + str(offset).strip("\x00 "))
            else:  # camera clock is assumed to be set to local trip time
                taken_at = naive.replace(tzinfo=default_tz)
        except ValueError:
            taken_at = None
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    if gps.get(2) and gps.get(4):
        try:
            latitude = _gps_coordinate(gps[2], gps.get(1, "N"))
            longitude = _gps_coordinate(gps[4], gps.get(3, "E"))
        except (TypeError, ValueError, ZeroDivisionError):
            latitude = longitude = None
    return taken_at, latitude, longitude


def process_photo(media):
    with Image.open(media_path(media.original.name)) as image:
        taken_at, latitude, longitude = exif_metadata(image.getexif(), media.entry.trip.tz)
        image = ImageOps.exif_transpose(image)
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        image = image.convert("RGBA" if has_alpha else "RGB")
        media.width, media.height = image.size
        derivatives = {}
        for name, edge in PHOTO_SIZES.items():
            copy = image.copy()
            copy.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            relative = derived_name(media, f"{name}.webp")
            media_path(relative).parent.mkdir(parents=True, exist_ok=True)
            copy.save(media_path(relative), "WEBP", quality=82, method=4)
            derivatives[name] = relative
    media.derivatives = derivatives
    media.taken_at = taken_at
    media.latitude, media.longitude = latitude, longitude


# Video and audio -------------------------------------------------------------

def run(cmd, timeout=3600):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {result.stderr.strip()[-1000:]}")
    return result.stdout


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-print_format", "json",
                           "-show_format", "-show_streams", str(path)], timeout=120))


ISO6709 = re.compile(r"^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


def probe_metadata(info):
    """(duration, taken_at, latitude, longitude) from ffprobe output."""
    tags = {k.lower(): v for k, v in (info.get("format", {}).get("tags") or {}).items()}
    duration = info.get("format", {}).get("duration")
    duration = float(duration) if duration else None
    taken_at = None
    for key in ("com.apple.quicktime.creationdate", "creation_time"):
        if tags.get(key):
            try:
                taken_at = datetime.fromisoformat(tags[key].replace("Z", "+00:00"))
                if taken_at.tzinfo is None:
                    taken_at = taken_at.replace(tzinfo=dt_timezone.utc)
                break
            except ValueError:
                pass
    latitude = longitude = None
    location = tags.get("com.apple.quicktime.location.iso6709") or tags.get("location")
    if location and (match := ISO6709.match(location)):
        latitude = Decimal(f"{float(match[1]):.6f}")
        longitude = Decimal(f"{float(match[2]):.6f}")
    return duration, taken_at, latitude, longitude


def process_video(media):
    source = media_path(media.original.name)
    info = probe(source)
    media.duration_seconds, media.taken_at, media.latitude, media.longitude = probe_metadata(info)

    mp4 = derived_name(media, "720.mp4")
    poster = derived_name(media, "poster.jpg")
    media_path(mp4).parent.mkdir(parents=True, exist_ok=True)
    partial = media_path(mp4 + ".partial.mp4")
    edge = VIDEO_SHORT_SIDE
    # Shorter side capped at 720 px (never upscaled), both sides even for H.264.
    scale = (
        f"scale='if(gte(iw,ih),-2,trunc(min({edge},iw)/2)*2)'"
        f":'if(gte(iw,ih),trunc(min({edge},ih)/2)*2,-2)'"
    )
    run(["ffmpeg", "-y", "-v", "error", "-i", str(source),
         "-map", "0:v:0", "-map", "0:a:0?", "-vf", scale,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(partial)])
    partial.replace(media_path(mp4))

    at = "1" if (media.duration_seconds or 0) > 1.5 else "0"
    run(["ffmpeg", "-y", "-v", "error", "-ss", at, "-i", str(media_path(mp4)),
         "-frames:v", "1", "-q:v", "3", str(media_path(poster))], timeout=120)

    out = probe(media_path(mp4))
    video = next(s for s in out["streams"] if s.get("codec_type") == "video")
    media.width, media.height = video.get("width"), video.get("height")
    media.derivatives = {"mp4": mp4, "poster": poster}


def process_audio(media):
    source = media_path(media.original.name)
    media.duration_seconds, media.taken_at, _, _ = probe_metadata(probe(source))
    if source.suffix.lower() in BROWSER_AUDIO:
        media.derivatives = {"audio": media.original.name}
        return
    target = derived_name(media, "audio.m4a")
    media_path(target).parent.mkdir(parents=True, exist_ok=True)
    partial = media_path(target + ".partial.m4a")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vn",
         "-c:a", "aac", "-b:a", "128k", str(partial)])
    partial.replace(media_path(target))
    media.derivatives = {"audio": target}
