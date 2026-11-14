# v4 #23: Read API

**Status:** implemented 2026-11-11 on branch `worktree-bridge-cse_01M7JK1AVzjArdXY3fjss2Va` (not deployed), tests in `api/tests_read.py`.

**Depends on:** #21

## Scope

- `GET /api/v1/trips` (member trips; `current: true` on the trip whose dates include today in its
  time zone), `GET /api/v1/trips/{id}` (incl. chapters, travellers, time zone, live-sharing settings).
- `GET /api/v1/trips/{id}/entries?updated_since=&cursor=`: entries with body (markdown + rendered
  HTML), place, coordinates, author, `source`, `is_public`, media list. Deleted entries come back as
  tombstones (`deleted: true`) when `updated_since` is given, so clients can sync.
- Media objects: kind, status, dimensions, `taken_at`, coordinates, and variant URLs under
  `/api/v1/media/{id}/{variant}`, which check permission and answer with `X-Accel-Redirect` like
  `serve_media` (works with session or token).
- `GET /api/v1/trips/{id}/map`: replaces `trips/<pk>/map.json` (same GeoJSON, incl. #18's photo
  features). Share-page equivalent `GET /api/v1/share/{token}/map` (no auth, public entries only).
- **Website moves over:** `trip-map.js` and `reader.js` fetch from the API; old `map.json` URLs
  redirect (301) for one release, then go.

## Acceptance Criteria

1. Non-members get 404 on every trip-scoped endpoint (not 403, matching the web).
2. The share map never contains private entries or their photos (port #6/#18 tests to the API).
3. `updated_since` returns entries changed or deleted after the timestamp, and nothing older.
4. Trip page and share page work in the browser, served entirely from the API (existing page tests pass).
