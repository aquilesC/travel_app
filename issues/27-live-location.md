# v4 #27: Live location with privacy controls

**Status:** implemented 2026-11-11 on branch `worktree-bridge-cse_01M7JK1AVzjArdXY3fjss2Va` (not deployed), tests in `api/tests_live.py`.

**Depends on:** #26

## Scope

- **Trip settings** (trip edit page + API): `live_share` = `off` | `members` (default) | `link`;
  `live_delay_minutes` (default 60, 0 allowed); `live_round_m` (default 1000, 0 = exact).
  Delay and rounding apply to share-link viewers only. Members always see exact, live data.
- **Privacy zones** per user (account page + `/api/v1/me`): circles (lat, lon, radius ≥ 200 m, label
  like "Home"). Positions inside a zone are never shown on any page (members included) and are cut
  from the live path. They are still stored for the owner's GPX export.
- `GET /api/v1/trips/{id}/live` (members) and `GET /api/v1/share/{token}/live` (link viewers when
  `live_share=link`): latest position per traveller + today's path, after delay/rounding/zones,
  plus `as_of` timestamp. Short cache (30 s) on the share variant.
- **Trip and share pages:** a live layer on the map (pulsing dot + "Updated 12 min ago"), polling
  every 60 s while the tab is visible. Hidden when there's no position in the last 24 h.
- Digest email: one line "Last seen near Ella, 18:40" when live sharing to link viewers is on.

## Acceptance Criteria

1. With `live_share=members`, the share live endpoint returns 404.
2. With `link`, 60 min delay and 1 km rounding: a viewer at 12:00 sees no point newer than 11:00,
   with coordinates snapped to the 1 km grid.
3. A point inside a privacy zone appears in no live response and no map path, for anyone.
4. Members see the exact latest point immediately.
5. The page stops polling when the tab is hidden (no requests in the server log for a background tab).
