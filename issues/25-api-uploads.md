# v4 #25: Upload API

**Status:** implemented 2026-11-11 on branch `worktree-bridge-cse_01M7JK1AVzjArdXY3fjss2Va` (not deployed), tests in `api/tests_write.py, trips/tests/test_media.py`.

**Depends on:** #21

Move the chunked-upload protocol from `trips/media.py` (start / status / chunk / complete) under the
API, keeping its semantics (≤ 50 MB chunks, offset check, 409 on mismatch) so it still passes
Cloudflare's 100 MB limit.

## Scope

- `POST /api/v1/uploads` `{filename, size, sha256, target: {entry_id | batch_id | none}, client_id}`
  → upload id. `target: none` creates a detached upload that an entry can claim later (#24
  `media_ids`). That lets the app upload media before the entry exists.
- `GET /api/v1/uploads/{id}` (received bytes), `PUT /api/v1/uploads/{id}/chunk?offset=`,
  `POST /api/v1/uploads/{id}/complete` → media id / import item id.
- `POST /api/v1/media/exists` `{sha256: [...]}` → which hashes the trip already has. The app skips
  those (photos already sent via WhatsApp, web or an earlier pick).
- Detached uploads not claimed within 7 days are deleted by the nightly job.
- **Website moves over:** `upload.js` uses the API endpoints; the old URLs are removed.
- Processing (HEIC, ffmpeg, audio) unchanged: the same worker task runs after `complete`.

## Acceptance Criteria

1. A 300 MB video uploads in 50 MB chunks and is processed.
2. Interrupting after chunk 3 and resuming from `GET …/uploads/{id}` finishes without re-sending chunks 1–3.
3. Completing an upload whose sha256 differs from the announced one fails with 422.
4. `media/exists` only reports hashes from trips the caller is a member of.
5. Web uploads on the entry editor and import pages still work (existing tests pass against the API).
