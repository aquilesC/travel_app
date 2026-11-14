"""WhatsApp ingest via Twilio: webhook, message → entry, replies.

Twilio posts one request per WhatsApp message (each photo is its own message).
The webhook only verifies and stores the raw message; the worker turns it into
an entry (grouping messages that arrive within WHATSAPP_GROUP_MINUTES).
"""

import base64
import hashlib
import hmac
import logging
import mimetypes
import tempfile
import urllib.parse
import urllib.request
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import Profile, normalize_whatsapp

from .models import Entry, InboundMessage, Trip
from .services import chapters as chapter_service
from .services import entries as entry_service
from .services.media import store_original

log = logging.getLogger(__name__)

CONTENT_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic",
    "video/mp4": ".mp4", "video/3gpp": ".3gp", "video/quicktime": ".mov",
    "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/amr": ".amr", "audio/aac": ".aac",
    "audio/mp4": ".m4a", "audio/opus": ".opus",
}
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


# Twilio request signing ------------------------------------------------------

def twilio_signature(url, params, token):
    """Twilio's scheme: HMAC-SHA1 over URL + each POST key and value, keys sorted."""
    data = url + "".join(f"{key}{value}" for key in sorted(params)
                         for value in sorted(params.getlist(key)
                                             if hasattr(params, "getlist") else [params[key]]))
    digest = hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def valid_signature(request):
    token = settings.TWILIO_AUTH_TOKEN
    given = request.headers.get("X-Twilio-Signature", "")
    if not token or not given:
        return False
    expected = twilio_signature(settings.TWILIO_WEBHOOK_URL, request.POST, token)
    return hmac.compare_digest(expected, given)


@csrf_exempt
@login_not_required
@require_POST
def twilio_webhook(request):
    from .tasks import process_inbound

    if not valid_signature(request):
        return HttpResponseForbidden("invalid signature")
    sid = request.POST.get("MessageSid") or request.POST.get("SmsMessageSid")
    if not sid:
        return HttpResponseBadRequest("missing MessageSid")
    payload = {key: request.POST.get(key) for key in request.POST}
    message, created = InboundMessage.objects.get_or_create(
        message_sid=sid,
        defaults={"from_number": normalize_whatsapp(payload.get("From")), "payload": payload},
    )
    if created:  # Twilio retries deliver the same MessageSid; process it once
        process_inbound.enqueue(message.pk)
    return HttpResponse(EMPTY_TWIML, content_type="text/xml")


# Outbound (Twilio REST) --------------------------------------------------------

def _twilio_auth_header():
    raw = f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def send_whatsapp(to_number, body):
    """Free-form reply; free inside the 24 h window opened by the sender's message."""
    if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_WHATSAPP_FROM):
        log.warning("Twilio not configured; would have replied to %s: %s", to_number, body)
        return
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    data = urllib.parse.urlencode({
        "From": settings.TWILIO_WHATSAPP_FROM, "To": f"whatsapp:{to_number}", "Body": body,
    }).encode()
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Authorization", _twilio_auth_header())
    try:
        with urllib.request.urlopen(request, timeout=20):
            pass
    except Exception:
        log.exception("WhatsApp reply to %s failed", to_number)


def download_media(url, target, max_bytes=None):
    """Stream a Twilio media URL to `target`. Auth is not forwarded on redirect."""
    max_bytes = max_bytes or settings.WHATSAPP_MEDIA_MAX_BYTES
    request = urllib.request.Request(url)
    request.add_unredirected_header("Authorization", _twilio_auth_header())
    written = 0
    with urllib.request.urlopen(request, timeout=60) as response, open(target, "wb") as fh:
        while block := response.read(1024 * 1024):
            written += len(block)
            if written > max_bytes:
                raise ValueError("media larger than the WhatsApp limit")
            fh.write(block)
    return written


# Message → entry -------------------------------------------------------------

def active_trip(when, user):
    """The user's trip whose dates (in its own zone) include `when`; latest start wins."""
    day = when.date()
    candidates = Trip.objects.filter(travellers=user, start_date__lte=day + timedelta(days=1),
                                     end_date__gte=day - timedelta(days=1))
    matches = [t for t in candidates if t.start_date <= when.astimezone(t.tz).date() <= t.end_date]
    return max(matches, key=lambda t: (t.start_date, t.pk)) if matches else None


def parse_commands(body):
    """Returns (text, chapter_title, force_new, private). Commands go on the first line."""
    lines = (body or "").strip().splitlines()
    chapter_title, force_new, private = None, False, False
    if lines:
        token, _, rest = lines[0].strip().partition(" ")
        command = token.lower()
        if command == "#chapter" and rest.strip():
            chapter_title, force_new, lines = rest.strip()[:200], True, lines[1:]
        elif command == "#new":
            force_new, lines = True, [rest, *lines[1:]]
        elif command == "#private":
            private, lines = True, [rest, *lines[1:]]
    return "\n".join(lines).strip(), chapter_title, force_new, private


def _decimal(value):
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, TypeError):
        return None


def entry_edit_url(entry):
    return settings.SITE_URL + reverse("entry_edit", args=[entry.pk])


def process_message(message_id, trip_id=None):
    message = InboundMessage.objects.get(pk=message_id)
    if message.status in (InboundMessage.PROCESSED, InboundMessage.REJECTED):
        return  # already handled (e.g. task retried)
    if message.status == InboundMessage.UNROUTED and trip_id is None:
        return

    number = normalize_whatsapp(message.payload.get("From"))
    profile = Profile.objects.select_related("user").filter(whatsapp_number=number).first()
    if profile is None:
        message.status = InboundMessage.REJECTED
        message.save(update_fields=["status"])
        log.warning("Rejected WhatsApp message from unknown number %s", number)
        return

    trip = (Trip.objects.filter(pk=trip_id, travellers=profile.user).first() if trip_id
            else active_trip(message.received_at, profile.user))
    if trip is None:
        message.status = InboundMessage.UNROUTED
        message.save(update_fields=["status"])
        recent = InboundMessage.objects.filter(
            from_number=number, status=InboundMessage.UNROUTED,
            received_at__gte=message.received_at - timedelta(minutes=settings.WHATSAPP_GROUP_MINUTES),
        ).exclude(pk=message.pk).exists()
        if not recent:
            send_whatsapp(number, "No trip is active today, so I saved this. "
                                  f"Assign it to a trip at {settings.SITE_URL}/")
        return

    try:
        with transaction.atomic():
            entry, created, notes = apply_message(message, trip, profile.user)
    except Exception as exc:
        log.exception("WhatsApp message %s failed", message.message_sid)
        message.status, message.error = InboundMessage.FAILED, f"{type(exc).__name__}: {exc}"
        message.save(update_fields=["status", "error"])
        return

    message.status, message.entry, message.error = InboundMessage.PROCESSED, entry, "\n".join(notes)
    message.save(update_fields=["status", "entry", "error"])
    if entry is None:
        send_whatsapp(number, notes[0] if notes else "OK")
    elif created:
        send_whatsapp(number, f"Added to {trip.title} ({entry_edit_url(entry)})")


def apply_message(message, trip, user):
    """Create or extend an entry from one message. Returns (entry|None, created, notes)."""
    payload = message.payload
    received_at = message.received_at
    text, chapter_title, force_new, private = parse_commands(payload.get("Body"))
    notes = []

    if chapter_title:
        chapter = chapter_service.create_chapter(user, trip, chapter_title, make_current=True)
        notes.append(f"Chapter “{chapter.title}” started in {trip.title}.")

    latitude, longitude = _decimal(payload.get("Latitude")), _decimal(payload.get("Longitude"))
    has_location = latitude is not None and longitude is not None
    num_media = int(payload.get("NumMedia") or 0)
    if not (text or has_location or num_media or private):
        return None, False, notes  # a bare command

    window = timedelta(minutes=settings.WHATSAPP_GROUP_MINUTES)
    entry = None
    if not force_new:
        entry = (Entry.objects.filter(trip=trip, author=user, source=Entry.SOURCE_WHATSAPP,
                                      chapter=trip.current_chapter,  # a new chapter starts fresh
                                      occurred_at__gte=received_at - window,
                                      occurred_at__lte=received_at)
                 .order_by("-occurred_at", "-id").first())
        if entry and has_location and entry.has_location:
            entry = None  # a second location is a new check-in
    created = entry is None
    fields = {}
    if text:
        fields["body"] = f"{entry.body if entry else ''}\n\n{text}".strip()
    if has_location:
        fields["latitude"], fields["longitude"] = latitude, longitude
        fields["place_name"] = (payload.get("Label") or payload.get("Address")
                                or (entry.place_name if entry else ""))[:200]
    if private:
        fields["is_public"] = False
    if created:
        entry = entry_service.create_entry(user, trip, source=Entry.SOURCE_WHATSAPP,
                                           chapter=trip.current_chapter, occurred_at=received_at,
                                           **fields)
    else:
        entry = entry_service.update_entry(user, entry, **fields)

    for index in range(num_media):
        url = payload.get(f"MediaUrl{index}")
        content_type = (payload.get(f"MediaContentType{index}") or "").split(";")[0].strip()
        if not url:
            continue
        ext = CONTENT_EXT.get(content_type) or mimetypes.guess_extension(content_type) or ""
        filename = f"whatsapp-{message.message_sid}-{index}{ext}"
        tmp_dir = Path(settings.MEDIA_ROOT) / "tmp" / "whatsapp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=tmp_dir, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            download_media(url, tmp_path)
            media, error = store_original(entry, tmp_path, filename, is_travel_copy=True,
                                          content_type=content_type)
            if error:
                notes.append(error)
        except Exception as exc:
            log.exception("Downloading %s failed", url)
            notes.append(f"Media {index} failed: {exc}")
        finally:
            tmp_path.unlink(missing_ok=True)
    return entry, created, notes
