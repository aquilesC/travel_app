"""Invites: create, (re)send, accept."""

import re
import secrets
import unicodedata
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Invite, display_name

MAX_PENDING = 20


class InviteError(ValueError):
    pass


def user_with_email(email):
    User = get_user_model()
    address = EmailAddress.objects.filter(email__iexact=email).select_related("user").first()
    return address.user if address else User.objects.filter(email__iexact=email).first()


def invite(inviter, email, trip=None):
    """Returns (kind, obj): ("added", user) | ("exists", user) | ("invited", Invite)."""
    from .tasks import send_added_email, send_invite_email

    existing = user_with_email(email)
    if existing:
        if trip is None:
            return "exists", existing
        trip.travellers.add(existing)
        send_added_email.enqueue(existing.pk, trip.pk, inviter.pk)
        return "added", existing

    pending = Invite.objects.filter(invited_by=inviter, accepted_at__isnull=True,
                                    expires_at__gt=timezone.now())
    if pending.count() >= MAX_PENDING:
        raise InviteError(f"You have {MAX_PENDING} open invites; revoke some first.")
    invite = pending.filter(email__iexact=email, trip=trip).first()
    if invite is None:
        invite = Invite.objects.create(
            email=email, invited_by=inviter, trip=trip, token=secrets.token_urlsafe(32),
            expires_at=timezone.now() + timedelta(days=Invite.VALID_DAYS),
        )
    send_invite_email.enqueue(invite.pk)
    return "invited", invite


def resend(invite):
    from .tasks import send_invite_email

    invite.expires_at = timezone.now() + timedelta(days=Invite.VALID_DAYS)
    invite.save(update_fields=["expires_at"])
    send_invite_email.enqueue(invite.pk)


def valid_invite(token):
    return (Invite.objects.select_related("trip", "invited_by")
            .filter(token=token, accepted_at__isnull=True, expires_at__gt=timezone.now()).first())


def unique_username(first_name, last_name, email):
    base = f"{first_name}{('-' + last_name) if last_name else ''}" or email.split("@")[0]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:30] or "traveller"
    User = get_user_model()
    candidate, n = base, 1
    while User.objects.filter(username=candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


@transaction.atomic
def accept(invite, *, first_name, last_name, password):
    invite = Invite.objects.select_for_update().get(pk=invite.pk)
    if invite.accepted_at or invite.expires_at < timezone.now():
        raise InviteError("This invite is no longer valid.")
    if user_with_email(invite.email):
        raise InviteError("An account with this email already exists. Log in instead.")
    User = get_user_model()
    user = User.objects.create_user(
        username=unique_username(first_name, last_name, invite.email), email=invite.email,
        password=password, first_name=first_name, last_name=last_name,
    )
    EmailAddress.objects.create(user=user, email=invite.email, verified=True, primary=True)
    if invite.trip_id:
        invite.trip.travellers.add(user)
    invite.accepted_at, invite.accepted_by = timezone.now(), user
    invite.save(update_fields=["accepted_at", "accepted_by"])
    return user


def send_mail_template(to, subject, template, context):
    message = EmailMultiAlternatives(subject=subject, body=render_to_string(f"email/{template}.txt", context), to=[to])
    message.attach_alternative(render_to_string(f"email/{template}.html", context), "text/html")
    message.send()


def inviter_name(user):
    return display_name(user)
