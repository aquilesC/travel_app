import secrets
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse


def new_token():
    return secrets.token_urlsafe(16)


def validate_timezone(value):
    if value not in available_timezones():
        raise ValidationError(f"Unknown time zone: {value}")


class Person(models.Model):
    """Someone we travel with (not an app user)."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "people"

    def __str__(self):
        return self.name


class Trip(models.Model):
    title = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    timezone = models.CharField(
        max_length=64, default="Europe/Amsterdam", validators=[validate_timezone],
        help_text="All times of this trip are shown in this zone, e.g. Asia/Colombo.",
    )
    description = models.TextField(blank=True, help_text="Markdown.")
    companions = models.ManyToManyField(Person, blank=True)
    # Which of the app's users went on this trip (counts toward their profile).
    travellers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="travelled_trips"
    )
    cover = models.ForeignKey(
        "Media", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Chapter that new WhatsApp entries go into (set by "#chapter ...").
    current_chapter = models.ForeignKey(
        "Chapter", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    share_token = models.CharField(max_length=32, unique=True, default=new_token)
    share_enabled = models.BooleanField(default=True)
    # Live location from the iPhone app (v4 #27).
    LIVE_OFF, LIVE_MEMBERS, LIVE_LINK = "off", "members", "link"
    LIVE_CHOICES = [(LIVE_OFF, "Nobody"), (LIVE_MEMBERS, "Members only"),
                    (LIVE_LINK, "Members, and everyone with the share link")]
    live_share = models.CharField(
        "Who sees where we are now", max_length=10, choices=LIVE_CHOICES, default=LIVE_MEMBERS,
        help_text="Members always see exact positions. Share-link viewers get the delay and rounding below.",
    )
    live_delay_minutes = models.PositiveIntegerField(
        "Delay for the share link (minutes)", default=60,
        help_text="Share-link viewers see where you were this long ago.",
    )
    live_round_m = models.PositiveIntegerField(
        "Rounding for the share link (metres)", default=1000,
        help_text="Share-link viewers see positions snapped to a grid this coarse. 0 = exact.",
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="trip_end_after_start",
            )
        ]

    def __str__(self):
        return self.title

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "The trip can't end before it starts."})

    @property
    def tz(self):
        return ZoneInfo(self.timezone)

    def get_absolute_url(self):
        return reverse("trip_detail", args=[self.pk])

    def share_url(self):
        return settings.SITE_URL + reverse("share_trip", args=[self.share_token])


class Chapter(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="chapters")
    title = models.CharField(max_length=200)
    position = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["trip", "position"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "position"], name="chapter_unique_position")
        ]

    def __str__(self):
        return self.title

    @classmethod
    def next_position(cls, trip):
        last = cls.objects.filter(trip=trip).aggregate(m=models.Max("position"))["m"]
        return 0 if last is None else last + 1


class Entry(models.Model):
    SOURCE_WEB = "web"
    SOURCE_WHATSAPP = "whatsapp"
    SOURCE_APP = "app"
    SOURCES = [(SOURCE_WEB, "web"), (SOURCE_WHATSAPP, "WhatsApp"), (SOURCE_APP, "iPhone app")]

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="entries")
    chapter = models.ForeignKey(Chapter, null=True, blank=True, on_delete=models.SET_NULL)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    occurred_at = models.DateTimeField(db_index=True)
    body = models.TextField(blank=True, help_text="Markdown.")
    place_name = models.CharField(max_length=200, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_public = models.BooleanField(
        default=True, help_text="Public entries appear on the share link and in emails."
    )
    source = models.CharField(max_length=10, choices=SOURCES, default=SOURCE_WEB)
    # Set by the app so a retried post doesn't create a second entry (v4 #24).
    client_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["occurred_at", "id"]
        verbose_name_plural = "entries"
        constraints = [models.UniqueConstraint(fields=["author", "client_id"], name="entry_unique_client_id")]

    def __str__(self):
        return f"{self.trip}: {self.occurred_at:%Y-%m-%d %H:%M}"

    def clean(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError("Give both latitude and longitude, or neither.")
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValidationError({"latitude": "Latitude must be between -90 and 90."})
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValidationError({"longitude": "Longitude must be between -180 and 180."})
        if self.chapter_id and self.chapter.trip_id != self.trip_id:
            raise ValidationError({"chapter": "That chapter belongs to another trip."})

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    def map_point(self):
        """(lat, lon) for the map: the entry's own location, else its first located photo."""
        if self.has_location:
            return float(self.latitude), float(self.longitude)
        for media in self.media.all():  # uses prefetched media when available
            if media.latitude is not None:
                return float(media.latitude), float(media.longitude)
        return None

    def get_absolute_url(self):
        return reverse("trip_detail", args=[self.trip_id]) + f"#entry-{self.pk}"


def original_upload_to(instance, filename):
    ext = Path(filename).suffix.lower()[:10]
    return f"originals/{instance.entry.trip_id}/{uuid.uuid4().hex}{ext}"


class Media(models.Model):
    PHOTO, VIDEO, AUDIO = "photo", "video", "audio"
    KINDS = [(PHOTO, "photo"), (VIDEO, "video"), (AUDIO, "audio")]
    PENDING, READY, FAILED = "pending", "ready", "failed"
    STATUSES = [(PENDING, "processing"), (READY, "ready"), (FAILED, "failed")]
    # Variants a client may request, per kind.
    VARIANTS = {
        PHOTO: {"original", "sm", "md", "lg"},
        VIDEO: {"original", "mp4", "poster"},
        AUDIO: {"original", "audio"},
    }

    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="media")
    kind = models.CharField(max_length=10, choices=KINDS)
    original = models.FileField(upload_to=original_upload_to, max_length=255)
    original_name = models.CharField(max_length=255, blank=True)
    is_travel_copy = models.BooleanField(
        default=False, help_text="Compressed copy received via WhatsApp."
    )
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    error = models.TextField(blank=True)
    derivatives = models.JSONField(default=dict, blank=True)
    sha256 = models.CharField(max_length=64, db_index=True)
    size_bytes = models.BigIntegerField()
    taken_at = models.DateTimeField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    LOCATION_SOURCES = [("exif", "from the file"), ("gpx", "from a GPX track"),
                        ("interpolated", "estimated from nearby photos")]
    location_source = models.CharField(max_length=12, choices=LOCATION_SOURCES, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name_plural = "media"

    def __str__(self):
        return f"{self.kind} {self.original_name or self.pk}"

    def variant_path(self, variant):
        """Path relative to MEDIA_ROOT for a variant, or None if not available."""
        if variant not in self.VARIANTS[self.kind]:
            return None
        if variant == "original":
            return self.original.name
        return self.derivatives.get(variant)


class Upload(models.Model):
    """A chunked upload (API: /api/v1/uploads, used by static/js/upload.js and the app).

    At most one of entry (entry editor) or batch (bulk import) is set. With neither, the
    upload is "detached": once complete it waits until an entry claims it (the app uploads
    media before posting the entry, v4 #24/#25). Unclaimed ones are deleted after a week.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    entry = models.ForeignKey(Entry, null=True, blank=True, on_delete=models.CASCADE, related_name="uploads")
    batch = models.ForeignKey("ImportBatch", null=True, blank=True, on_delete=models.CASCADE,
                              related_name="uploads")
    trip = models.ForeignKey(Trip, null=True, blank=True, on_delete=models.CASCADE, related_name="+",
                             help_text="For detached uploads: the trip it's meant for.")
    filename = models.CharField(max_length=255)
    size = models.BigIntegerField()
    sha256 = models.CharField(max_length=64, blank=True, help_text="Announced by the client; checked on completion.")
    client_id = models.UUIDField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["created_by", "client_id"], name="upload_unique_client_id")]

    @property
    def temp_path(self):
        return Path(settings.MEDIA_ROOT) / "tmp" / "uploads" / f"{self.id}.part"

    @property
    def received(self):
        try:
            return self.temp_path.stat().st_size
        except FileNotFoundError:
            return 0


class ImportBatch(models.Model):
    """Photos staged for a bulk import, into an existing trip or a new one."""

    OPEN, DONE = "open", "done"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    trip = models.ForeignKey(Trip, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="imports")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, default=OPEN)
    client_id = models.UUIDField(null=True, blank=True)  # the app's retry key (v4 #28)
    entry_ids = models.JSONField(default=list, blank=True)  # filled on commit, so a retry gets the same answer
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["created_by", "client_id"], name="importbatch_unique_client_id")]

    def __str__(self):
        return f"Import into {self.trip or 'a new trip'} ({self.items.count()} files)"


class ImportItem(models.Model):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="items")
    path = models.CharField(max_length=255)  # relative to MEDIA_ROOT
    original_name = models.CharField(max_length=255)
    kind = models.CharField(max_length=10, choices=Media.KINDS)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.BigIntegerField()
    # Capture time exactly as the camera wrote it, stored with a UTC label only
    # because the column needs one: the wall-clock value is what matters. The
    # real UTC offset is in taken_offset_minutes when the file records one
    # (phones do; most cameras don't).
    taken_local = models.DateTimeField(null=True, blank=True)
    taken_offset_minutes = models.IntegerField(null=True, blank=True)
    camera = models.CharField(max_length=120, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ["taken_local", "id"]


class Track(models.Model):
    MODES = [
        ("sail", "sailing"), ("bike", "cycling"), ("hike", "hiking"), ("walk", "walking"),
        ("car", "car"), ("transit", "public transport"), ("other", "other"),
    ]

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="tracks")
    chapter = models.ForeignKey(Chapter, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=200, blank=True)
    mode = models.CharField(max_length=10, choices=MODES, default="other")
    # Verbatim upload: the source of truth. Parsed only when rendering.
    gpx_text = models.TextField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.name or f"{self.get_mode_display()} track"


class Subscriber(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="subscribers")
    email = models.EmailField()
    token = models.CharField(max_length=32, unique=True, default=new_token)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    last_digest_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["trip", "email"], name="subscriber_unique_email")
        ]

    def __str__(self):
        return f"{self.email} → {self.trip}"

    @property
    def is_active(self):
        return self.confirmed_at is not None and self.unsubscribed_at is None


class InboundMessage(models.Model):
    """Raw Twilio webhook: idempotency key and a record that nothing is lost."""

    RECEIVED, PROCESSED, UNROUTED, REJECTED, FAILED = (
        "received", "processed", "unrouted", "rejected", "failed",
    )
    STATUSES = [(s, s) for s in (RECEIVED, PROCESSED, UNROUTED, REJECTED, FAILED)]

    message_sid = models.CharField(max_length=64, unique=True)
    from_number = models.CharField(max_length=40)
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=STATUSES, default=RECEIVED)
    entry = models.ForeignKey(Entry, null=True, blank=True, on_delete=models.SET_NULL)
    error = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_at"]

    def __str__(self):
        return f"{self.message_sid} ({self.status})"


class ScheduledRun(models.Model):
    """Last day a scheduled job was enqueued, so restarts don't run it twice."""

    name = models.CharField(max_length=50, unique=True)
    last_run_date = models.DateField()


class Position(models.Model):
    """A point recorded by a traveller's phone (iPhone app, v4 #26). GPX tracks stay separate."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="positions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="positions")
    recorded_at = models.DateTimeField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = models.FloatField(null=True, blank=True)
    altitude_m = models.FloatField(null=True, blank=True)
    speed_mps = models.FloatField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recorded_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "recorded_at"], name="position_unique_user_time"),
        ]
        indexes = [models.Index(fields=["trip", "user", "recorded_at"], name="position_trip_user_time")]

    def __str__(self):
        return f"{self.user} @ {self.recorded_at:%Y-%m-%d %H:%M:%S}"


class Tombstone(models.Model):
    """Remembers deleted entries so the app's incremental sync can drop them (v4 #23)."""

    trip_id = models.IntegerField(db_index=True)  # plain int: the trip itself may be gone
    model = models.CharField(max_length=20)  # "entry"
    object_id = models.IntegerField()
    deleted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.model} {self.object_id} deleted {self.deleted_at:%Y-%m-%d %H:%M}"
