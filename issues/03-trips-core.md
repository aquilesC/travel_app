# v1 #3: Trips core

**Status:** implemented 2026-11-09, tests in `trips/tests/` (`accounts/tests.py` for #2), verified on the live stack.

Part of epic [00-epic-v1-travel-journal.md](00-epic-v1-travel-journal.md): v1 travel journal for Sri Lanka (departure 2026-12-21). Data model, locked decisions and timeline live in the epic.

**Depends on (epic child numbers):** #2

## Scope

- Models `Person`, `Trip`, `Chapter`, `Entry` with migrations and admin.
- Web UI (login required), base template, mobile-first CSS (no framework):
  - `/` trip list (newest first), "new trip".
  - `/trips/<id>/` timeline: entries grouped by chapter, ordered by `occurred_at`, times in trip TZ;
    filter "public only / all".
  - Create/edit/delete forms for trip, chapter (incl. reorder by position), entry (body markdown
    with preview, occurred_at in trip TZ, place name, lat/lon, is_public, chapter).
- Markdown rendering via `markdown` + `nh3` allowlist sanitising.

## Acceptance Criteria (numbering from the epic)

2b. An entry time entered as 18:00 in a trip with time zone `Asia/Colombo` is stored as 12:30 UTC
   and displayed as 18:00; a trip with `end_date` before `start_date` is rejected; a `<script>`
   tag in entry markdown is stripped from the rendered HTML.
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
