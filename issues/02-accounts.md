# v1 #2: Accounts

**Status:** implemented 2026-11-09, tests in `trips/tests/` (`accounts/tests.py` for #2), verified on the live stack.

Part of epic [00-epic-v1-travel-journal.md](00-epic-v1-travel-journal.md): v1 travel journal for Sri Lanka (departure 2026-12-21). Data model, locked decisions and timeline live in the epic.

**Depends on (epic child numbers):** —

## Scope

- App `accounts`: `Profile` model (above), created by signal on user creation; admin inline.
- Django auth views at `/accounts/login/`, `/accounts/logout/`; `LOGIN_URL`, `LOGIN_REDIRECT_URL="/"`.
- All non-public views require login. No self-signup; users created via `createsuperuser`/admin.

## Acceptance Criteria (numbering from the epic)

2. Anonymous request to any page except `/s/<token>/…`, `/healthz/`, `/accounts/login/`,
   `/hooks/twilio/…` and subscribe/confirm/unsubscribe URLs redirects to login.
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
