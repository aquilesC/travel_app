"""Chunked, resumable uploads (v4 #25). Cloudflare caps requests at 100 MB, so files go up
in chunks of at most UPLOAD_CHUNK_MAX_BYTES and are joined here."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from ..access import ensure_member
from ..models import Media, Upload
from .errors import Invalid, NotFound
from .media import kind_for, sha256_of, store_original

DETACHED_TTL = timedelta(days=7)


class Conflict(Exception):
    """The client is out of sync; `received` says where to resume."""

    def __init__(self, message, received=None):
        super().__init__(message)
        self.received = received


def get_upload(actor, upload_id):
    upload = (Upload.objects.select_related("entry__trip", "batch__trip", "trip")
              .filter(pk=upload_id, created_by=actor).first())
    if upload is None:
        raise NotFound("No such upload.")
    return upload


def start_upload(actor, *, filename, size, sha256="", entry=None, batch=None, trip=None, client_id=None):
    """Returns (upload, created). With a known client_id the earlier upload comes back."""
    if client_id:
        existing = Upload.objects.filter(created_by=actor, client_id=client_id).first()
        if existing:
            return existing, False
    filename = str(filename or "")[:255]
    if not filename or not size or size <= 0:
        raise Invalid("Missing file name or size.")
    if kind_for(filename) is None:
        raise Invalid({"filename": [f"Unsupported file type: {filename}"]})
    if sum(x is not None for x in (entry, batch)) > 1:
        raise Invalid("Upload into an entry or an import, not both.")
    if entry is not None:
        ensure_member(actor, entry.trip)
    if trip is not None:
        ensure_member(actor, trip)
    upload = Upload.objects.create(entry=entry, batch=batch, trip=trip, filename=filename, size=size,
                                   sha256=(sha256 or "").lower(), client_id=client_id, created_by=actor)
    upload.temp_path.parent.mkdir(parents=True, exist_ok=True)
    upload.temp_path.touch()
    return upload, True


def receive_chunk(actor, upload, offset, read, length):
    """Append `length` bytes from `read(n)` at `offset`. Returns the new received size."""
    if upload.completed_at:
        raise Conflict("Upload already complete.", upload.received)
    received = upload.received
    if offset != received:
        raise Conflict("offset mismatch", received)  # e.g. a retried chunk: resume from `received`
    if length <= 0 or length > settings.UPLOAD_CHUNK_MAX_BYTES:
        raise Invalid("Chunk too large or empty.")
    if received + length > upload.size:
        raise Invalid("More data than announced.")
    with open(upload.temp_path, "ab") as fh:
        remaining = length
        while remaining:
            block = read(min(remaining, 1024 * 1024))
            if not block:
                break
            fh.write(block)
            remaining -= len(block)
    if remaining:
        # Connection dropped mid-chunk: drop the partial bytes so a retry lines up.
        with open(upload.temp_path, "r+b") as fh:
            fh.truncate(received)
        raise Conflict("Incomplete chunk.", received)
    return received + length


def _discard(upload):
    upload.temp_path.unlink(missing_ok=True)
    upload.delete()


def complete_upload(actor, upload):
    """Finish an upload. Returns one of:
    {"media_id", "sha256", "size"} (entry), {"item_id", ...} or {"skipped"} (import),
    {"upload_id", "sha256", "size"} (detached: waits for an entry to claim it).
    """
    if upload.completed_at:  # repeated call (e.g. the response got lost)
        return {"upload_id": str(upload.pk), "sha256": upload.sha256, "size": upload.size}
    if upload.received != upload.size:
        raise Conflict("Upload incomplete.", upload.received)
    digest = sha256_of(upload.temp_path)
    if upload.sha256 and upload.sha256 != digest:
        _discard(upload)
        raise Invalid({"sha256": ["The file doesn't match the announced SHA-256; upload it again."]})

    if upload.batch_id:
        from ..importing import stage_file

        item, error = stage_file(upload.batch, upload.temp_path, upload.filename)
        _discard(upload)
        if error:  # duplicates are skipped, not failures
            return {"skipped": error}
        return {"item_id": item.pk, "sha256": item.sha256, "size": item.size_bytes}

    if upload.entry_id:
        ensure_member(actor, upload.entry.trip)
        media, error = store_original(upload.entry, upload.temp_path, upload.filename)
        if error:
            _discard(upload)
            raise Conflict(error)
        upload.delete()
        return {"media_id": media.pk, "sha256": media.sha256, "size": media.size_bytes}

    upload.sha256, upload.completed_at = digest, timezone.now()
    upload.save(update_fields=["sha256", "completed_at"])
    return {"upload_id": str(upload.pk), "sha256": digest, "size": upload.size}


def claim_uploads(actor, entry, upload_ids):
    """Attach completed detached uploads to an entry, in the given order. Returns the media.

    Unknown or unfinished ids raise Invalid before anything is attached. A file already
    on the entry (same SHA-256) is dropped silently: retries are expected.
    """
    ensure_member(actor, entry.trip)
    uploads = {str(u.pk): u for u in Upload.objects.filter(
        pk__in=upload_ids, created_by=actor, entry=None, batch=None)}
    missing = [str(i) for i in upload_ids if str(i) not in uploads or not uploads[str(i)].completed_at]
    if missing:
        raise Invalid({"upload_ids": [f"Unknown or unfinished uploads: {', '.join(missing)}"]})
    created = []
    for upload_id in upload_ids:
        upload = uploads[str(upload_id)]
        media, error = store_original(entry, upload.temp_path, upload.filename)
        if media:
            created.append(media)
        _discard(upload)
    return created


def existing_hashes(actor, hashes, trip=None):
    """Which of these SHA-256s are already in trips the actor is a member of (or in `trip`)."""
    hashes = {h.lower() for h in hashes}
    qs = Media.objects.filter(sha256__in=hashes, entry__trip__travellers=actor)
    if trip is not None:
        qs = qs.filter(entry__trip=trip)
    return sorted(set(qs.values_list("sha256", flat=True)))


def delete_stale_uploads(now=None):
    """Nightly: unclaimed detached uploads after a week, and abandoned partial ones."""
    cutoff = (now or timezone.now()) - DETACHED_TTL
    stale = Upload.objects.filter(created_at__lt=cutoff, entry=None, batch=None)
    count = 0
    for upload in stale:
        _discard(upload)
        count += 1
    return count
