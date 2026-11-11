"""Trips belong to their members (Trip.travellers). Non-members get 404."""

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404

from .models import Trip


def member_trips(user):
    return Trip.objects.filter(travellers=user)


def get_trip(user, pk, queryset=None):
    base = queryset if queryset is not None else Trip.objects.all()  # don't evaluate a queryset
    return get_object_or_404(base.filter(travellers=user), pk=pk)


def get_owned(user, model_or_qs, **lookup):
    """Fetch a Chapter/Entry/Track/Media… whose trip the user is a member of."""
    qs = model_or_qs.objects.all() if hasattr(model_or_qs, "objects") else model_or_qs
    field = "entry__trip__travellers" if qs.model.__name__ == "Media" else "trip__travellers"
    return get_object_or_404(qs, **{field: user}, **lookup)


def fellow_travellers(user):
    """Users you can add to a trip: yourself and people you already share a trip with."""
    return get_user_model().objects.filter(
        Q(pk=user.pk) | Q(travelled_trips__travellers=user), is_active=True
    ).distinct().order_by("first_name", "username")
