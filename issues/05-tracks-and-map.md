# v1 #5: Tracks & map

**Status:** implemented 2026-11-09, tests in `trips/tests/` (`accounts/tests.py` for #2), verified on the live stack.

Part of epic [00-epic-v1-travel-journal.md](00-epic-v1-travel-journal.md): v1 travel journal for Sri Lanka (departure 2026-12-21). Data model, locked decisions and timeline live in the epic.

**Depends on (epic child numbers):** #3

## Scope

- Upload GPX (file input; ≤ 50 MB) into `Track.gpx_text`, with mode/name/chapter. Reject files
  `gpxpy` can't parse, with the parser error.
- `track_geojson(track)`: parse with `gpxpy`, simplify (Ramer–Douglas–Peucker, ~10 m tolerance),
  return GeoJSON LineString + stats (distance km, duration, elevation gain). Cached in Django
  cache (key `track:<id>:<updated_at>`); `CACHES` uses the database cache backend.
- Trip map (MapLibre + OpenFreeMap "liberty" style): tracks coloured by mode, entry check-in
  points with popups linking to the entry, fit bounds to all features. Rendered on the trip page.

## Acceptance Criteria (numbering from the epic)

5. A 100k-point GPX renders on the trip map in under 3 s on first view and under 300 ms when
   cached; the stored `gpx_text` is byte-identical to the upload.
- Each test states its card: `protects=<observable it protects>; fails_when=<wrong result it rejects>; no_claim=<what green does not prove>`
- No degradation of existing functionality (`/healthz/`, admin).

## Rules for the implementing agent

1. Acceptance criteria are the `protects / fails_when / no_claim` profile of each test: the observable it protects, the wrong result it rejects, and what green does not prove. Never "make the tests pass".
2. Real code and real tests land in the same change; a placeholder, a stub assertion or a test deferred to a follow-up is not done.
3. Any change to a test, validator, CI step, timeout, tolerance, threshold, snapshot or suppression pragma is reported on its own line in your summary with its justification, before any other result.
4. A reported command names the command and its observed result (exit status, counts, the failing line); a command you did not run is not reported, and stderr is never silenced in a command you cite.
5. Your report is a claim until the parent re-executes it: say what you verified, what you reused, and what you could not check.

## Rollback

Revert the PR; v1 migrations are additive (`migrate <app> <previous>` before reverting code).
