# v3 #16: Invites

**Status:** implemented 2026-11-11, tests in `accounts/tests_auth.py` and `trips/tests/test_membership.py`, verified on the live stack.

**Depends on:** #14, #15

## Scope

- `/invites/`: any user invites by email, optionally to one of their trips; lists their invites
  (pending / accepted / expired) with "copy link", "resend" and "revoke".
- `Invite(email, invited_by, trip?, token, created_at, expires_at = +14 days, accepted_at, accepted_by)`.
- If the email already belongs to a user: with a trip, they're added as a member and get a
  "you were added" email; without a trip nothing is sent ("already has an account").
- Otherwise an email (worker task) with `/invite/<token>/`. That page asks for name and password
  (email fixed), creates the account (unique username from the name), a verified `EmailAddress`,
  logs in, joins the trip, marks the invite accepted, and redirects to the trip (or home).
- Invalid, expired, revoked or used links show a friendly page; a logged-in user opening someone
  else's invite is told to log out first.
- At most 20 pending invites per user.

## Acceptance Criteria

1. Invite to a trip → accept with name + password → logged in, member of that trip, invite accepted.
2. The same link a second time, or after 14 days, shows the "no longer valid" page and creates nothing.
3. Inviting an existing user's email to a trip adds them directly and sends no invite link.
4. The invite page is reachable without login; the password must pass Django's validators.
