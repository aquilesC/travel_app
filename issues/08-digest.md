# v1 #8: Subscriptions & daily digest

**Status:** implemented 2026-11-09, tests in `trips/tests/` (`accounts/tests.py` for #2), verified on the live stack.

Part of epic [00-epic-v1-travel-journal.md](00-epic-v1-travel-journal.md): v1 travel journal for Sri Lanka (departure 2026-12-21). Data model, locked decisions and timeline live in the epic.

**Depends on (epic child numbers):** #1, #6

## Scope

- Mailgun SMTP via Django SMTP backend in `MAILERS` (env `EMAIL_HOST/PORT/USER/PASSWORD`,
  `DEFAULT_FROM_EMAIL` = a `trips` mailbox on the aquiles.me domain, set in `.env`). Console backend when `DJANGO_DEBUG=true`.
- Subscribe form on share page → `Subscriber` + confirmation email; unconfirmed rows expire after
  7 days. Every email has a one-click unsubscribe link and `List-Unsubscribe` header.
- `send_daily_digests` task (20:00 Europe/Amsterdam): per confirmed subscriber, public entries
  created since `last_digest_at` (or confirmation); skip if none; HTML + text email with entry
  text excerpt, up to 6 thumbnails, link to share page. Updates `last_digest_at` after send.

## Acceptance Criteria (numbering from the epic)

11. Digest: a confirmed subscriber gets exactly one email per day with new public entries, none on
    days without entries, none after unsubscribing; unconfirmed subscribers get none.
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
