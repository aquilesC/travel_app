# ios #2: Login and trip picker

**Status:** code written 2026-11-11, not yet built in Xcode. Login/logout in `TripsKit/AuthService.swift` (tested against the dev server); Keychain store, login screen, trip picker and 401 handling in `TripsApp/` (not compiled yet).

**Depends on:** #1, v4 #22, v4 #23

## Scope

- Login screen: email + password → allauth headless app login → token stored in Keychain
  (`kSecAttrAccessibleAfterFirstUnlock`, so background uploads can read it). Device name sent for the
  session list on the website.
- "Forgot password" opens the website's reset page in `SFSafariViewController`.
- Any 401 from the API → back to login, queued work kept (#5).
- Trip picker: `GET /api/v1/trips`, the `current` trip pre-selected; the active trip is remembered.
  Shows title, dates, time zone, cover.
- Clock skew warning if the phone's clock differs from `health.server_time` by > 2 min.
- Logout clears token and local caches but asks first if the outbox isn't empty.

## Acceptance Criteria

1. Fresh install → login → current trip selected without extra taps.
2. Wrong password shows an inline error; rate-limited login shows "Try again in a few minutes".
3. Signing the session out on the website makes the app return to login on its next request.
