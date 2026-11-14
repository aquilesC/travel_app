# v4 #26: Positions

**Status:** implemented 2026-11-11 on branch `worktree-bridge-cse_01M7JK1AVzjArdXY3fjss2Va` (not deployed), tests in `api/tests_positions.py`.

**Depends on:** #21

The app records position at a user-chosen interval and sends it in batches. GPX `Track`s stay for
uploaded files; positions are a separate source.

## Scope

- Model `Position(trip, user, recorded_at, latitude, longitude, accuracy_m, altitude_m null,
  speed_mps null, received_at)`; unique `(user, recorded_at)`; index `(trip, user, recorded_at)`.
- `POST /api/v1/trips/{id}/positions` `{points: [...]}` (≤ 5000 per request). Duplicates are ignored.
  Points outside the trip's dates (± 1 day) or with accuracy worse than 500 m are rejected
  individually. Returns `{accepted, duplicates, rejected}`.
- `GET /api/v1/trips/{id}/positions?user=&since=` (members) for the app to show its own path.
- Trip map: each traveller's position path as a line (simplified with the same approach as
  `gpx.py`, cached), styled differently from GPX tracks. Gaps > 30 min break the line.
- `GET /api/v1/trips/{id}/positions.gpx?user=&date=` → GPX export (for the archive and other tools).
- `importing.py`: `track_series` also takes a user's positions, so `fill_locations` places
  photos without GPS from the phone's log (used by #28).
- Trip page shows "Recorded by app: 14.2 km today" per traveller (reuse `stats.py`).

## Acceptance Criteria

1. Posting the same batch twice stores each point once.
2. A batch with 3 bad points out of 100 stores 97 and reports 3 rejected.
3. Path renders on the trip map; GPX export opens in a GPX viewer and has the same point count.
4. A photo without GPS taken at 10:05 gets the position recorded closest to it (±10 min), as with GPX today.
5. Positions are never on the share page through this endpoint (live view is #27).
