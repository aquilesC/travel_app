# v4 #24: Write API (entries, chapters, tracks)

**Status:** implemented 2026-11-11 on branch `worktree-bridge-cse_01M7JK1AVzjArdXY3fjss2Va` (not deployed), tests in `api/tests_write.py`.

**Depends on:** #23 (and #25 for attaching media)

## Scope

- `POST /api/v1/trips/{id}/entries`: body (markdown), `occurred_at`, place name, lat/lon, `is_public`,
  optional chapter (default: the trip's current chapter), `upload_ids` (completed detached uploads
  from #25, attached in order), `client_id`. `source="app"` when
  token-authenticated, `"web"` otherwise. Repeating a `client_id` returns the existing entry (200, not 201).
- `PATCH /api/v1/entries/{id}`, `DELETE /api/v1/entries/{id}`: author or any trip member, as on the web.
- Chapters: create, rename, reorder, delete; `POST /api/v1/trips/{id}/chapters/current`, the same
  "current chapter" the WhatsApp `#chapter` command sets.
- `POST /api/v1/trips/{id}/tracks`: GPX upload (multipart, ≤ 20 MB) stored verbatim in `Track.gpx_text`.
- All of it goes through the #20 services; WhatsApp and the web editor behave identically.
- An app post's `occurred_at` is the time it was written on the phone, not the upload time.

## Acceptance Criteria

1. Posting the same `client_id` twice creates one entry.
2. An entry posted from the app shows on the trip page with its media, location and correct local time.
3. An entry with `is_public=false` never appears on the share page or in the digest.
4. Invalid coordinates / dates outside the trip → 422 with field errors.
