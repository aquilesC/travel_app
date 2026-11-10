# v2 #12: Create a trip from GPX tracks

**Status:** implemented 2026-11-10, tests in `accounts/tests_profile.py` and `trips/tests/test_imports.py`, verified on the live stack.

**Depends on:** —

## Scope

- Home → "New trip from GPX" → `/trips/from-gpx/`: one or more GPX files (≤ 50 MB each),
  travel mode, time zone, optional title.
- Each file becomes a `Track` (stored verbatim). Track name from the GPX `<name>` or file name.
- Trip dates = first/last GPX timestamp converted to the chosen time zone. If no file has
  timestamps, start/end dates are required in the form.
- Title defaults to the first track's name, else "Trip <start date>".
- Invalid files are reported by name and nothing is created (all-or-nothing).

## Acceptance Criteria

1. Two GPX files spanning 2026-12-23 06:00Z → 2026-12-25 18:00Z with zone Asia/Colombo create a
   trip from 2026-12-23 to 2026-12-25 (23:30 local on the 25th) with 2 tracks.
2. Files without timestamps and no dates in the form → form error, nothing created.
3. One broken file among valid ones → error naming it, nothing created.
