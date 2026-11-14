from django.db import transaction

from ..access import ensure_member, fellow_travellers
from ..models import Person, Trip, new_token
from ._util import validated
from .errors import Invalid

TRIP_FIELDS = ("title", "start_date", "end_date", "timezone", "description", "share_enabled",
               "live_share", "live_delay_minutes", "live_round_m")


def _allowed_travellers(actor, trip, travellers):
    allowed = set(fellow_travellers(actor).values_list("pk", flat=True))
    if trip.pk:
        allowed |= set(trip.travellers.values_list("pk", flat=True))
    if any(u.pk not in allowed for u in travellers):
        raise Invalid({"travellers": ["You can only add people you already travel with."]})


def _set_people(trip, travellers, companions, new_companion_names):
    if travellers is not None:
        if not travellers:
            raise Invalid({"travellers": ["A trip needs at least one member."]})
        trip.travellers.set(travellers)
    if companions is not None:
        trip.companions.set(companions)
    for name in new_companion_names or ():
        name = name.strip()
        if name:
            trip.companions.add(Person.objects.get_or_create(name=name[:100])[0])


@transaction.atomic
def create_trip(actor, *, travellers=None, companions=None, new_companion_names=(), **fields):
    trip = Trip(created_by=actor, **{k: v for k, v in fields.items() if k in TRIP_FIELDS})
    validated(trip)
    travellers = list(travellers) if travellers is not None else [actor]
    _allowed_travellers(actor, trip, travellers)
    trip.save()
    _set_people(trip, travellers, companions, new_companion_names)
    trip.travellers.add(actor)  # the creator is always a member
    return trip


@transaction.atomic
def update_trip(actor, trip, *, travellers=None, companions=None, new_companion_names=(), **fields):
    """Fields left out are unchanged. Removing yourself from travellers means leaving the trip."""
    ensure_member(actor, trip)
    for key, value in fields.items():
        if key in TRIP_FIELDS:
            setattr(trip, key, value)
    validated(trip)
    if travellers is not None:
        travellers = list(travellers)
        _allowed_travellers(actor, trip, travellers)
    trip.save()
    _set_people(trip, travellers, companions, new_companion_names)
    return trip


def delete_trip(actor, trip):
    ensure_member(actor, trip)
    trip.delete()


def regenerate_share_token(actor, trip):
    ensure_member(actor, trip)
    trip.share_token = new_token()
    trip.save(update_fields=["share_token", "updated_at"])
    return trip.share_token
