# v4 #30: Tailwind page migration

**Status:** planned

**Depends on:** #29

## Scope

Migrate every template to Tailwind utilities + #29 components, then delete `legacy.css`.

- **Reader:** `trip_detail.html`, `share_trip.html`, `_timeline.html`, `_story_bar.html`, `_map.html`
  (keep #18 behaviour: sticky map ≥ 1100 px, map toggle on mobile, photo viewer, reduced motion).
  MapLibre's own CSS stays as is.
- **Editing:** `trip_form`, `entry_form`, `track_form`, `simple_form`, `confirm_delete`, `trip_from_gpx`.
- **Imports:** `import_upload`, `import_review`.
- **Home & landing:** `home.html`, `landing.html`, `404.html`, `500.html`.
- **Accounts:** `account`, `invites`, `invite_accept`, `invite_invalid`, `public_profile`,
  `templates/allauth/layouts/base.html`.
- **Subscriptions:** `subscribe_result`, `unsubscribe`.
- Emails (`templates/email/`, `trips/templates/email/`) keep inline CSS. Not in scope.
- JS that toggles class names (`reader.js`, `trip-map.js`, `upload.js`) updated to the new classes.

## Acceptance Criteria

1. `legacy.css` deleted; `grep -rn "class=\"topbar\|class=\"muted" templates trips accounts` is empty.
2. `/qa` pass on the live-like stack: trip page, share page, editor, import flow, account, invite,
   at 390 px and 1440 px, light and dark. No layout regressions.
3. Pages work without JavaScript as before (#18 criterion 3).
4. Lighthouse accessibility ≥ 95 on trip and share pages.
