"""Bulk imports: staged photos → grouped entries (logic in trips/importing.py)."""

from .. import importing
from ..access import ensure_member, is_member
from ..models import ImportBatch
from .errors import NotFound


def start_import(actor, trip=None, client_id=None):
    if trip is not None:
        ensure_member(actor, trip)
    if client_id:
        existing = ImportBatch.objects.filter(created_by=actor, client_id=client_id).first()
        if existing:
            return existing
    return ImportBatch.objects.create(trip=trip, created_by=actor, client_id=client_id)


def get_batch(actor, batch_id):
    """Any import the actor started, open or done (the API reports both)."""
    batch = ImportBatch.objects.select_related("trip").filter(pk=batch_id, created_by=actor).first()
    if batch is None or (batch.trip_id and not is_member(actor, batch.trip)):
        raise NotFound("No such import.")
    return batch


def preview(actor, batch, shifts=None):
    """The entries a commit would create: [{"start", "end", "latitude", "longitude", "item_ids"}].

    Photos without GPS are placed from the trip's GPX tracks and the importing user's
    recorded positions, exactly as the commit will do.
    """
    shifts = shifts or {}
    items = list(batch.items.all())
    series = importing.location_series(batch.trip, actor) if batch.trip_id else []
    tz = batch.trip.tz if batch.trip_id else importing.ZoneInfo(importing.guess_timezone(items))
    dated, undated = importing.build_points(items, tz, shifts, series)
    groups = importing.group_points(dated) + ([undated] if undated else [])
    result = []
    for group in groups:
        located = next((p for p in group if p.lat is not None), None)
        times = [p.utc for p in group if p.utc]
        result.append({
            "start": min(times) if times else None, "end": max(times) if times else None,
            "latitude": located.lat if located else None, "longitude": located.lon if located else None,
            "item_ids": [p.item.pk for p in group],
            "located_from": sorted({p.source for p in group if p.source}),
        })
    return result


def open_batch(actor, batch_id):
    """An open import the actor started (and, for a trip import, is still a member of)."""
    batch = (ImportBatch.objects.select_related("trip")
             .filter(pk=batch_id, status=ImportBatch.OPEN, created_by=actor).first())
    if batch is None or (batch.trip_id and not is_member(actor, batch.trip)):
        raise NotFound("No such import.")
    return batch


def commit_into_trip(actor, batch, *, shifts, make_public):
    ensure_member(actor, batch.trip)
    return importing.create_entries(batch, batch.trip, shifts, make_public, actor)


def commit_as_new_trip(actor, batch, *, title, tz_name, travellers, gpx_texts, shifts, make_public):
    return importing.create_trip_from_batch(
        batch, title=title, tz_name=tz_name, travellers=travellers, gpx_texts=gpx_texts,
        shifts=shifts, make_public=make_public, author=actor,
    )


def discard(actor, batch):
    open_batch(actor, batch.pk)
    importing.discard_batch(batch)


def trip_from_gpx(actor, **kwargs):
    return importing.create_trip_from_gpx(author=actor, **kwargs)
