# ios #8: Trip status screen and settings

**Status:** code written 2026-11-11, not yet built in Xcode. Trip screen, settings, diagnostics export (current app run's log only). Not compiled yet.

**Depends on:** #2, #3

## Scope

- **Trip screen** (home of the app): trip title + day "Day 6 of 14", recording toggle and state,
  today's distance and point count, last position upload ("Shared 4 min ago"), outbox count,
  map of today's path, buttons: Post, Photos, Open trip on web.
- **Settings:** recording interval, upload interval, large files on wifi only, auto-start recording,
  account (name, logout), server URL (Debug builds only), app version + API version.
- **Diagnostics:** export the last 24 h of logs (`OSLogStore`) as a file to share. This helps when tuning #9.

## Acceptance Criteria

1. Every number on the trip screen updates live while the app is open.
2. Changing the recording interval applies without restarting recording.
3. Diagnostics export produces a file with location and upload events from the last 24 h.
