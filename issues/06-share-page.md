# v1 #6: Public share page

**Status:** implemented 2026-11-09, tests in `trips/tests/` (`accounts/tests.py` for #2), verified on the live stack.

Part of epic [00-epic-v1-travel-journal.md](00-epic-v1-travel-journal.md): v1 travel journal for Sri Lanka (departure 2026-12-21). Data model, locked decisions and timeline live in the epic.

**Depends on (epic child numbers):** #4, #5

## Scope

- `/s/<share_token>/`: read-only trip page (title, dates, companions, chapters, public entries,
  map with tracks and public entry points). 404 if token unknown or `share_enabled=False`.
- Media requests from the share page authorised by token + `entry.is_public`; private entry media
  returns 404 even with a guessed path.
- `<meta name="robots" content="noindex">`; owner can regenerate the token (old link dies).
- "Subscribe to updates" form (wired in #8).

## Acceptance Criteria (numbering from the epic)

6. Share link shows public entries only; fetching a private entry's media URL with the share
   token returns 404; disabling sharing makes the link 404.
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
