# ios #4: Batched position upload (live sharing)

**Status:** code written 2026-11-11, not yet built in Xcode. Batch uploader with backoff tested with a fake server and end-to-end against the dev server. Triggers: location updates, foreground, network change, BGProcessingTask.

**Depends on:** #2, #3, v4 #26 (v4 #27 for the website's live view)

## Scope

- **Upload interval setting:** 5, 15, 30, 60 min (default 15). Allowed on cellular (batches are a few KB).
- On each location update, if `now − lastUpload ≥ uploadInterval`, send all unsent points
  (`POST /api/v1/trips/{id}/positions`, ≤ 5000 per request, oldest first) and mark them sent on success.
  Also on app foreground and when connectivity returns (`NWPathMonitor`).
- Failures: exponential backoff (1, 2, 4… up to the upload interval); 4xx for individual points
  are logged and those points are dropped, not retried forever.
- "Send now" button on the status screen.
- Trip settings for live sharing (off / members / link, delay, rounding) are shown read-only with
  a link to the website to change them (v4 #27).

## Acceptance Criteria

1. In airplane mode for 2 hours, points accumulate. When back online they upload in one or a few
   batches and the website shows the full path.
2. With a 15-min upload interval, the member view on the website is never more than ~20 min behind
   while the phone is moving.
3. A server-side duplicate (retry after a timeout) doesn't create duplicates (server idempotency).
