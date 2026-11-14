"""Trips belong to their members (Trip.travellers). Non-members get NotFound (404)."""

from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import Trip
from .services.errors import NotFound


def member_trips(user):
    return Trip.objects.filter(travellers=user)


def is_member(user, trip):
    return trip.travellers.filter(pk=user.pk).exists()


def ensure_member(user, trip):
    if not (user.is_authenticated and is_member(user, trip)):
        raise NotFound("No such trip.")


def get_trip(user, pk, queryset=None):
    base = queryset if queryset is not None else Trip.objects.all()  # don't evaluate a queryset
    trip = base.filter(travellers=user, pk=pk).first()
    if trip is None:
        raise NotFound("No such trip.")
    return trip


def get_owned(user, model_or_qs, **lookup):
    """Fetch a Chapter/Entry/Track/Media… whose trip the user is a member of."""
    qs = model_or_qs.objects.all() if hasattr(model_or_qs, "objects") else model_or_qs
    field = "entry__trip__travellers" if qs.model.__name__ == "Media" else "trip__travellers"
    obj = qs.filter(**{field: user}, **lookup).first()
    if obj is None:
        raise NotFound(f"No such {qs.model._meta.verbose_name}.")
    return obj


def fellow_travellers(user):
    """Users you can add to a trip: yourself and people you already share a trip with."""
    return get_user_model().objects.filter(
        Q(pk=user.pk) | Q(travelled_trips__travellers=user), is_active=True
    ).distinct().order_by("first_name", "username")
