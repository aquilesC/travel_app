# v3 #17: Landing page and error pages

**Status:** implemented 2026-11-11, tests in `accounts/tests_auth.py` and `trips/tests/test_membership.py`, verified on the live stack.

**Depends on:** #14

## Scope

- `/` for visitors: a landing page (hero with an animated route line, what the app does in four
  short blocks: WhatsApp journaling, maps & GPX, photo imports, sharing with family; "invite only"
  note; log-in button). Logged-in users keep seeing their trips.
- `404.html`: "This path isn't on the map" with a compass illustration and links home / back.
- `500.html`: static (no template context), same tone.
- Both work in light and dark mode and at phone width.

## Acceptance Criteria

1. Anonymous `/` returns 200 with the landing page and a link to log in; logged-in `/` shows trips.
2. An unknown URL returns 404 with the custom page (when `DEBUG` is off).
3. `500.html` renders without a request context.
