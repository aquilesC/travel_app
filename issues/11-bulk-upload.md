# v2 #11: Bulk photo upload to a trip

**Status:** implemented 2026-11-10, tests in `accounts/tests_profile.py` and `trips/tests/test_imports.py`, verified on the live stack.

**Depends on:** — (shares the import pipeline with #13)

## Scope

- Trip page → "Add photos" → `/trips/<id>/import/`: drop many photos/videos; they go up with the
  existing chunked uploader into an `ImportBatch` (staging, not yet entries).
- On each completed upload, metadata is read immediately: capture time (EXIF / QuickTime),
  UTC offset if present, GPS, camera (make + model). Stored on an `ImportItem`.
- Preview page: number of files, per-camera time shift (± hours:minutes), how many have a location,
  "make entries public" checkbox. Duplicates (same sha256 already in the trip or batch) are
  skipped and listed.
- "Create entries":
  1. Times: EXIF offset if present, else local time in the trip's zone, plus the camera shift.
  2. Missing locations are filled (see #13 "Interpolation"), recording `Media.location_source`.
  3. Grouping: by time; a new entry starts when the gap to the previous photo is > 60 min or the
     photo is > 2 km from the entry's first located photo.
  4. One entry per group (occurred_at = first photo, location = first located photo), media in
     time order, processing enqueued. Batch marked done; files stay where they were uploaded.
- Discarding a batch deletes its files.
- Processing (`trips/processing.py`) no longer overwrites taken_at/location already set.

## Acceptance Criteria

1. 6 photos: 3 at 10:00–10:20 in Kandy, 2 at 14:00 in Kandy, 1 at 14:10 5 km away → 3 entries.
2. A camera shift of −1:00 moves that camera's photos one hour earlier before grouping.
3. Re-importing a photo already in the trip skips it and reports it.
4. Discard deletes the staged files and the batch.
