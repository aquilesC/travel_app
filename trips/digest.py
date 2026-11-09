"""Subscription confirmation and the daily digest email."""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Prefetch
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Media, Subscriber

log = logging.getLogger(__name__)
UNCONFIRMED_TTL = timedelta(days=7)
MAX_THUMBNAILS = 6


def absolute(path):
    return settings.SITE_URL + path


def _send(subscriber, subject, template, context):
    unsubscribe_url = absolute(reverse("subscription_unsubscribe", args=[subscriber.token]))
    context = {**context, "subscriber": subscriber, "trip": subscriber.trip,
               "unsubscribe_url": unsubscribe_url,
               "share_url": subscriber.trip.share_url()}
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string(f"email/{template}.txt", context),
        to=[subscriber.email],
        headers={
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )
    message.attach_alternative(render_to_string(f"email/{template}.html", context), "text/html")
    message.send()


def send_confirmation(subscriber_id):
    subscriber = Subscriber.objects.select_related("trip").get(pk=subscriber_id)
    if subscriber.confirmed_at or subscriber.unsubscribed_at:
        return
    confirm_url = absolute(reverse("subscription_confirm", args=[subscriber.token]))
    _send(subscriber, f"Confirm updates from “{subscriber.trip.title}”", "confirm",
          {"confirm_url": confirm_url})


def new_entries(subscriber, until):
    since = subscriber.last_digest_at or subscriber.confirmed_at
    return (
        subscriber.trip.entries.filter(is_public=True, created_at__gt=since, created_at__lte=until)
        .prefetch_related(Prefetch("media", queryset=Media.objects.filter(
            kind=Media.PHOTO, status=Media.READY).order_by("position", "id")))
        .order_by("occurred_at", "id")
    )


def send_digests(now=None):
    """One email per active subscriber with the public entries added since the last one."""
    now = now or timezone.now()
    Subscriber.objects.filter(confirmed_at__isnull=True,
                              created_at__lt=now - UNCONFIRMED_TTL).delete()
    sent = 0
    active = Subscriber.objects.select_related("trip").filter(
        confirmed_at__isnull=False, unsubscribed_at__isnull=True, trip__share_enabled=True)
    for subscriber in active:
        entries = list(new_entries(subscriber, now))
        if not entries:
            continue
        token = subscriber.trip.share_token
        thumbnails = [
            absolute(reverse("share_media", args=[token, m.pk, "sm"]))
            for entry in entries for m in entry.media.all()
        ][:MAX_THUMBNAILS]
        timezone.activate(subscriber.trip.tz)
        try:
            _send(subscriber, f"News from “{subscriber.trip.title}”", "digest",
                  {"entries": entries, "thumbnails": thumbnails})
        except Exception:
            log.exception("Digest to subscriber %s failed", subscriber.pk)
            continue
        finally:
            timezone.deactivate()
        subscriber.last_digest_at = now
        subscriber.save(update_fields=["last_digest_at"])
        sent += 1
    log.info("Sent %d digests", sent)
    return sent
