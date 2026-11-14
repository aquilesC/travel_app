from uuid import UUID

from django.conf import settings
from ninja import Field, Router, Schema

from trips.access import get_owned, get_trip
from trips.models import Entry
from trips.services import imports as import_service
from trips.services import uploads as service

from ..errors import ApiError
from ..schemas import ErrorOut

router = Router(tags=["uploads"])


class UploadIn(Schema):
    filename: str = Field(max_length=255)
    size: int = Field(gt=0)
    sha256: str | None = Field(None, pattern="^[0-9a-fA-F]{64}$", description="Checked on completion.")
    entry_id: int | None = Field(None, description="Attach to this entry when complete.")
    batch_id: UUID | None = Field(None, description="Add to this import when complete.")
    trip_id: int | None = Field(None, description="Detached upload for this trip; an entry claims it later.")
    client_id: UUID | None = None


class UploadOut(Schema):
    id: UUID
    received: int
    size: int
    chunk_size: int
    complete: bool


class ChunkOut(Schema):
    received: int


class CompleteOut(Schema):
    media_id: int | None = None
    item_id: int | None = None
    upload_id: UUID | None = None
    skipped: str | None = None
    sha256: str | None = None
    size: int | None = None


class HashesIn(Schema):
    sha256: list[str] = Field(max_length=5000)
    trip_id: int | None = None


class HashesOut(Schema):
    existing: list[str]


def _out(upload):
    return {"id": upload.pk, "received": upload.received, "size": upload.size,
            "chunk_size": settings.UPLOAD_CHUNK_MAX_BYTES, "complete": upload.completed_at is not None}


def _conflict(exc):
    extra = {"received": exc.received} if exc.received is not None else {}
    return ApiError(409, str(exc), code="conflict", **extra)


@router.post("/uploads", response={200: UploadOut, 201: UploadOut})
def start_upload(request, payload: UploadIn):
    """Start a chunked upload. Then PUT chunks, then POST complete. Repeating a `client_id`
    returns the existing upload, so the client can resume from `received`."""
    user = request.user
    entry = get_owned(user, Entry.objects.select_related("trip"), pk=payload.entry_id) if payload.entry_id else None
    batch = import_service.open_batch(user, payload.batch_id) if payload.batch_id else None
    trip = get_trip(user, payload.trip_id) if payload.trip_id else None
    upload, created = service.start_upload(
        user, filename=payload.filename, size=payload.size, sha256=payload.sha256 or "",
        entry=entry, batch=batch, trip=trip, client_id=payload.client_id)
    return (201 if created else 200), _out(upload)


@router.get("/uploads/{upload_id}", response=UploadOut)
def upload_status(request, upload_id: UUID):
    return _out(service.get_upload(request.user, upload_id))


BINARY_BODY = {"requestBody": {"required": True, "content": {
    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}}


@router.put("/uploads/{upload_id}/chunk", response={200: ChunkOut, 409: ErrorOut}, openapi_extra=BINARY_BODY)
def upload_chunk(request, upload_id: UUID, offset: int):
    """Raw bytes (Content-Type: application/octet-stream) starting at `offset`.
    409 with `received` means: continue from there."""
    upload = service.get_upload(request.user, upload_id)
    length = int(request.META.get("CONTENT_LENGTH") or 0)
    if length > settings.UPLOAD_CHUNK_MAX_BYTES:
        raise ApiError(413, "Chunk too large.")
    try:
        received = service.receive_chunk(request.user, upload, offset, request.read, length)
    except service.Conflict as exc:
        raise _conflict(exc) from None
    return {"received": received}


@router.post("/uploads/{upload_id}/complete", response={200: CompleteOut, 409: ErrorOut, 422: ErrorOut})
def upload_complete(request, upload_id: UUID):
    upload = service.get_upload(request.user, upload_id)
    try:
        return service.complete_upload(request.user, upload)
    except service.Conflict as exc:
        raise _conflict(exc) from None


@router.post("/media/exists", response=HashesOut)
def media_exists(request, payload: HashesIn):
    """Which of these files (by SHA-256) are already in your trips, so the app can skip them."""
    trip = get_trip(request.user, payload.trip_id) if payload.trip_id else None
    return {"existing": service.existing_hashes(request.user, payload.sha256, trip)}
