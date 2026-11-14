# ios #5: Offline outbox and resumable uploads

**Status:** code written 2026-11-11, not yet built in Xcode. Outbox tested (resume after a dropped connection, restart, wifi rule, no duplicates). Deviation: chunks go through the normal URLSession while the app runs, plus a BGProcessingTask to resume, instead of a background URLSession per chunk; revisit if the field test shows stalled uploads.

**Depends on:** #2, v4 #25

One queue for everything the app sends except positions (#4): media uploads, entries, import commits.

## Scope

- SwiftData `OutboxItem(kind, clientId UUID, payload, files, state, attempts, lastError, createdAt)`.
  Items run in order per entry (media uploads before the entry that references them).
- Media: compute SHA-256, `POST /api/v1/media/exists` to skip known files, then chunked upload
  (50 MB) through a **background `URLSession`** (upload-from-file per chunk), so uploads continue when
  the app is suspended. Resume from the server's `received` offset.
- **Network policy:** setting "Large files only on wifi" (default on, > 20 MB); text and small
  photos go on cellular. Per-item "Send now anyway" override.
- Outbox screen: pending items with progress, errors, retry, delete.
- Everything uses `client_id` so retries are idempotent end to end.

## Acceptance Criteria

1. Record a 2-min video offline, post it, go online on wifi: it uploads in the background with the
   app closed, and the entry appears on the website with the video.
2. Switching networks mid-upload resumes from the last confirmed chunk.
3. A photo already on the server (same SHA-256) is not uploaded again.
4. Force-quitting the app loses nothing in the outbox.
