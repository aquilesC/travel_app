# v4 #20: Service layer

**Status:** implemented 2026-11-11 on branch `worktree-bridge-cse_01M7JK1AVzjArdXY3fjss2Va` (not deployed), tests in `trips/tests/test_services.py`.

**Depends on:** —

Today domain rules are spread over `trips/views.py`, `trips/media.py`, `trips/imports.py` and
`trips/whatsapp.py` (`apply_message` creates chapters/entries/media itself). The API would be a fourth
copy. Move the rules into plain functions that views, the API and WhatsApp all call.

## Scope

- New package `trips/services/` with modules per area: `trips.py`, `chapters.py`, `entries.py`,
  `media.py`, `tracks.py`, `imports.py` (wrapping `importing.py`), `sharing.py`.
- Services take `(actor, …)` and return model instances. They enforce membership (reuse
  `trips/access.py` rules) and raise domain errors (`NotFound`, `Forbidden`, `Invalid` in
  `trips/services/errors.py`) instead of `Http404`/`get_object_or_404`. Views map them to 404/403.
- Validation that lives in forms today (dates, time zone, coordinates) moves to services; forms
  call services and keep only presentation.
- `whatsapp.apply_message` uses `entries.create_entry` / `media.attach_file` / `chapters.create_chapter`.
- `Entry.source` choices gain `"app"` (migration), ready for #24.
- No URL, template or behaviour changes.

## Acceptance Criteria

1. No view in `trips/` or `accounts/` writes to the database directly, except through services or forms
   that call services.
2. The full existing test suite passes unchanged.
3. New unit tests per service cover the membership rules: a non-member gets `NotFound` for every
   read and write.
4. `grep -n "objects.create" trips/whatsapp.py trips/views.py trips/imports.py` returns nothing.
