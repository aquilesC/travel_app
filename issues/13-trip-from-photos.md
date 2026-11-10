# v2 #13: Create a trip from photos

**Status:** implemented 2026-11-10, tests in `accounts/tests_profile.py` and `trips/tests/test_imports.py`, verified on the live stack.

**Depends on:** #11 (import pipeline), #12 (GPX parsing)

## Scope

- Home → "New trip from photos" → `/imports/new/`: same uploader as #11, batch without a trip.
- Preview adds: detected date range, time zone (default guessed: the most common EXIF UTC offset
  mapped to a zone with that offset, user can change), title, travellers, optional GPX files.
- "Create trip": trip from the dates (in the chosen zone), GPX files become tracks, then the #11
  steps create entries.

## Interpolation (used by #11 and #13)

For a photo without GPS, in this order:
1. **GPX**: if a track of the trip covers the photo time (±10 min), position interpolated
   linearly between the two track points around that time. `location_source = "gpx"`.
2. **Neighbours**: located photos before and after within 6 h each → linear interpolation in
   time between them; only one side within 1 h → copy it. `location_source = "interpolated"`.
3. Otherwise no location.

Photos with their own GPS keep it (`location_source = "exif"`).

## Acceptance Criteria

1. Photos with GPS at 10:00 (A) and 12:00 (B) and one without at 11:00 → midpoint of A and B.
2. With a GPX track covering 11:00, the GPX position wins over neighbour interpolation.
3. A photo 8 h from any located photo and outside any track stays without location.
4. Creating a trip from 5 photos dated 2026-12-22…2026-12-24 (+05:30) creates a trip with those
   dates in Asia/Colombo, entries grouped per #11, and the GPX tracks attached.
