# v1 #7: WhatsApp ingest (Twilio)

**Status:** implemented 2026-11-09, tests in `trips/tests/` (`accounts/tests.py` for #2), verified on the live stack.

Part of epic [00-epic-v1-travel-journal.md](00-epic-v1-travel-journal.md): v1 travel journal for Sri Lanka (departure 2026-12-21). Data model, locked decisions and timeline live in the epic.

**Depends on (epic child numbers):** #1, #3, #4

## Scope

- `POST /hooks/twilio/whatsapp/`: validate `X-Twilio-Signature` (reject 403), store
  `InboundMessage` (idempotent on `MessageSid`), return 200 fast, enqueue `process_inbound(id)`.
- Sender allowlist: `From` must match a `Profile.whatsapp_number`, else `rejected`, no reply.
- Routing: trip with `start_date ≤ today (trip TZ) ≤ end_date`; if several, latest `start_date`.
  None → `unrouted`, reply "No active trip; saved, assign it on the web" (unrouted messages listed
  in the UI and assignable to a trip).
- Grouping: append to the sender's latest `whatsapp` entry in that trip if it was created
  ≤ 10 min ago and the message isn't `#new`; else create a new entry (`occurred_at` = receive time).
- Content: text → appended to body; `MediaUrl*` → downloaded with Twilio basic auth into
  `Media(is_travel_copy=True)` and processed via #4; WhatsApp location (`Latitude`/`Longitude`,
  optional `Address`/`Label`) → sets entry lat/lon/place_name (new entry if current one already
  has a location); voice note → audio media.
- Commands (first token of body): `#chapter <title>` creates a chapter and makes it current for
  the trip; `#new` forces a new entry; `#private` sets `is_public=False` on the current entry.
- Reply (within 24 h service window, free of Meta fees): "Added to <trip> (<edit url>)", one reply
  per entry, not per message.
- Settings: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`.

## Acceptance Criteria (numbering from the epic)

7. Twilio webhook with an invalid signature returns 403 and stores nothing; a replayed
   `MessageSid` creates no duplicate entry.
8. Message from a number not in a Profile creates no entry and sends no reply.
9. Sending 5 photos + a caption within 2 minutes produces exactly one entry with 5 media items and
   one reply; `#new` then a text produces a second entry; `#chapter Galle` creates chapter "Galle"
   and later entries attach to it.
10. A message on a date with no active trip is stored as `unrouted` and can be assigned on the web.
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
