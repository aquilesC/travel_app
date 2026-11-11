# v3 #18: Trip reading experience

**Status:** implemented 2026-11-11, tests in `accounts/tests_auth.py` and `trips/tests/test_membership.py`, verified on the live stack.

**Depends on:** —

Applies to the member trip page and the public share page.

## Scope

- **Layout:** ≥ 1100 px: story column + sticky full-height map beside it. Narrower: map on top
  (40 vh, sticky) with a "Map" toggle button.
- **Photos on the map:** every located photo is a dot (clustered with counts when zoomed out);
  the photos of the entry you're reading show as round thumbnails. Clicking a dot or thumbnail
  opens that photo in the viewer.
- **Map follows the story:** as an entry scrolls into view the map flies to it (instant with
  `prefers-reduced-motion`) and highlights it. Clicking an entry point on the map scrolls to it.
- **Chapter navigation:** a sticky bar at the top of the story with a chapter menu and the current
  chapter highlighted; each chapter ends with "Next chapter: … →".
- **Entry navigation:** `j`/`k` (or ↓/↑ buttons on the bar) jump to the next/previous entry.
- **Photo viewer:** full-screen dialog over all photos and videos of the trip in order; ←/→ keys,
  swipe, Esc; shows "n / N", date, place and chapter; "Go to entry" closes it at that entry.
- Map data gains photo features (thumbnail URL, entry id), respecting share/private rules.

## Acceptance Criteria

1. map.json includes one `photo` feature per located photo of visible entries, with a thumbnail
   URL that works in that context (member URL or share URL); private entries' photos are absent
   on the share map.
2. Every entry in the timeline carries its coordinates (entry location, else first photo GPS).
3. The page works without JavaScript (story readable, photos link to full size).
