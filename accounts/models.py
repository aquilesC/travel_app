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
        max_length=20, unique=True, null=True, blank=True, validators=[validate_e164]
    )

    def save(self, *args, **kwargs):
        self.whatsapp_number = normalize_whatsapp(self.whatsapp_number) or None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Profile of {self.user}"


def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
