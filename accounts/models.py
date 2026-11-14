import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def validate_e164(value):
    if not E164.match(value):
        raise ValidationError("Use international format: + country code and number, no spaces.")


def normalize_whatsapp(value):
    """'whatsapp:+31 6 1234' -> '+316 1234' without separators."""
    value = (value or "").strip()
    if value.lower().startswith("whatsapp:"):
        value = value[len("whatsapp:"):]
    return re.sub(r"[\s\-().]", "", value)


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    # Messages from this number are accepted by the WhatsApp ingest.
    whatsapp_number = models.CharField(
        max_length=20, unique=True, null=True, blank=True, validators=[validate_e164],
        help_text="International format, e.g. +31612345678. Only this number can post via WhatsApp.",
    )
    # Path relative to MEDIA_ROOT of the 512×512 WebP avatar.
    avatar = models.CharField(max_length=255, blank=True)
    is_public = models.BooleanField(
        default=True, verbose_name="Public profile",
        help_text="Anyone can see your name, picture, trip count and km at /u/<username>/.",
    )

    def save(self, *args, **kwargs):
        self.whatsapp_number = normalize_whatsapp(self.whatsapp_number) or None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Profile of {self.user}"


class Invite(models.Model):
    VALID_DAYS = 14

    email = models.EmailField()
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name="invites_sent")
    trip = models.ForeignKey("trips.Trip", null=True, blank=True, on_delete=models.SET_NULL)
    token = models.CharField(max_length=43, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite for {self.email}"

    @property
    def status(self):
        from django.utils import timezone

        if self.accepted_at:
            return "accepted"
        return "expired" if self.expires_at < timezone.now() else "pending"

    def url(self):
        from django.urls import reverse

        return settings.SITE_URL + reverse("invite_accept", args=[self.token])


def display_name(user):
    return user.get_full_name() or user.username


def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


class PrivacyZone(models.Model):
    """A circle (e.g. home) where the user's recorded positions are never shown (v4 #27)."""

    MIN_RADIUS_M = 200

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="privacy_zones")
    label = models.CharField(max_length=60, default="Home")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    radius_m = models.PositiveIntegerField(default=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.label} ({self.radius_m} m)"

    def clean(self):
        if self.radius_m is not None and self.radius_m < self.MIN_RADIUS_M:
            raise ValidationError({"radius_m": f"Use at least {self.MIN_RADIUS_M} m."})
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValidationError({"latitude": "Latitude must be between -90 and 90."})
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValidationError({"longitude": "Longitude must be between -180 and 180."})
