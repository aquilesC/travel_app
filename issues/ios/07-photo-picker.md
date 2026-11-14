# ios #7: Photo picker with time and map filters

**Status:** code written 2026-11-11, not yet built in Xcode. Day / time-window / map-area filters and path placement tested in `PhotoFilterTests.swift`; picker screen with full-access and one-by-one fallback. Import flow tested end-to-end. Performance on a 30k library not measured yet.

**Depends on:** #5, v4 #25, v4 #28

Not a bulk upload: make it quick to find and pick the photos that belong in the journal.

## Scope

- Needs full photo-library access (the limited system picker can't filter by location); explain why
  on the permission screen, and fall back to `PhotosPicker` if access is limited.
- **Time filter:** day chips for each trip day (in the trip's time zone), plus a time-window slider
  within the day. Default: today.
- **Map filter:** MapKit map of the filtered photos (clustered pins, the day's recorded path from #3
  drawn underneath). Panning/zooming or drawing an area filters the grid.
- Photos without GPS are placed on the path by their timestamp (same idea as the server) and marked.
- Grid with multi-select, "select all in view", count + total size; already-uploaded photos marked
  (SHA-256 cache + `media/exists`).
- **Upload:** creates an import batch (v4 #28), queues originals in the outbox. iCloud-only originals
  are downloaded first (`isNetworkAccessAllowed`), respecting the wifi setting.
- When the batch is processed: notification "12 photos ready to review" → opens `review_url` in
  `SFSafariViewController`.

## Acceptance Criteria

1. Picking "Day 3, 14:00–18:00, area around the temple" shows only matching photos in under 1 s for a
   library of 30,000 photos.
2. Selected photos upload as originals and appear as grouped drafts on the website's review page.
3. Photos already in the trip can't be uploaded twice.
4. Works with "Optimize iPhone Storage" on (originals fetched from iCloud).
