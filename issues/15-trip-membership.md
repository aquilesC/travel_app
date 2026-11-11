# v3 #15: Trips belong to their members

**Status:** implemented 2026-11-11, tests in `accounts/tests_auth.py` and `trips/tests/test_membership.py`, verified on the live stack.

**Depends on:** —

## Scope

- A trip's members are its `travellers`. Members see and edit the trip, its chapters, entries,
  media, tracks and imports; everyone else gets 404 (not 403, to not reveal ids).
- Applies to every owner view, map data, media files, uploads, imports, the trip form's member list
  (choices: you + people you share a trip with), unrouted WhatsApp messages (only your own number's),
  WhatsApp routing (only trips where the sender is a member) and the home page.
- Creating a trip (any way) always makes the creator a member. A trip must keep ≥ 1 member.
- Share links, public profiles and the admin are unchanged.

## Acceptance Criteria

1. A non-member gets 404 on the trip page, map.json, entry edit, media file, upload start and
   import review of someone else's trip; the home page doesn't list it.
2. A WhatsApp message from a user is never routed to a trip they're not a member of.
3. The trip form refuses an empty member list.
