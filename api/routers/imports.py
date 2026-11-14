"""Imports from the app (v4 #28): picked photos → proposed entries → commit or web review."""

from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.urls import reverse
from ninja import Field, Router, Schema

from trips.access import get_trip
from trips.models import ImportBatch
from trips.services import imports as service

from ..errors import ApiError

router = Router(tags=["imports"])


class ImportIn(Schema):
    client_id: UUID | None = None


class ItemOut(Schema):
    id: int
    original_name: str
    kind: str
    sha256: str
    size_bytes: int
    camera: str
    latitude: float | None
    longitude: float | None


class ProposedEntry(Schema):
    start: datetime | None
    end: datetime | None
    latitude: float | None
    longitude: float | None
    item_ids: list[int]
    located_from: list[str] = Field(description="exif, gpx (GPX tracks or recorded positions), interpolated")


class ImportOut(Schema):
    id: UUID
    trip_id: int | None
    status: str
    review_url: str | None
    items: list[ItemOut]
    proposed_entries: list[ProposedEntry]
    entry_ids: list[int]


class CommitIn(Schema):
    make_public: bool = True


class CommitOut(Schema):
    entry_ids: list[int]


def _out(request, batch):
    is_open = batch.status == ImportBatch.OPEN
    items = list(batch.items.all()) if is_open else []
    return {
        "id": batch.pk, "trip_id": batch.trip_id, "status": batch.status,
        "review_url": settings.SITE_URL + reverse("import_review", args=[batch.pk]) if is_open else None,
        "items": [{"id": i.pk, "original_name": i.original_name, "kind": i.kind, "sha256": i.sha256,
                   "size_bytes": i.size_bytes, "camera": i.camera,
                   "latitude": None if i.latitude is None else float(i.latitude),
                   "longitude": None if i.longitude is None else float(i.longitude)} for i in items],
        "proposed_entries": service.preview(request.user, batch) if items else [],
        "entry_ids": batch.entry_ids,
    }


@router.post("/trips/{trip_id}/imports", response={201: ImportOut})
def start_import(request, trip_id: int, payload: ImportIn):
    """Open an import into a trip. Upload files with `batch_id` set, then commit (or review on the web)."""
    trip = get_trip(request.user, trip_id)
    return 201, _out(request, service.start_import(request.user, trip, client_id=payload.client_id))


@router.get("/imports/{batch_id}", response=ImportOut)
def import_detail(request, batch_id: UUID):
    return _out(request, service.get_batch(request.user, batch_id))


@router.post("/imports/{batch_id}/commit", response=CommitOut)
def commit_import(request, batch_id: UUID, payload: CommitIn):
    """Create the proposed entries. Committing again returns the same entries."""
    batch = service.get_batch(request.user, batch_id)
    if batch.status == ImportBatch.DONE:
        return {"entry_ids": batch.entry_ids}
    if batch.trip_id is None:
        raise ApiError(409, "Imports that create a new trip are finished on the website.", code="conflict")
    if not batch.items.exists():
        raise ApiError(409, "Nothing uploaded yet.", code="conflict")
    entries = service.commit_into_trip(request.user, batch, shifts={}, make_public=payload.make_public)
    return {"entry_ids": [e.pk for e in entries]}


@router.delete("/imports/{batch_id}", response={204: None})
def discard_import(request, batch_id: UUID):
    batch = service.open_batch(request.user, batch_id)
    service.discard(request.user, batch)
    return 204, None
