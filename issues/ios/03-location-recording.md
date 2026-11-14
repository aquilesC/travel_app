# ios #3: Location recording at a user-set interval

**Status:** code written 2026-11-11, not yet built in Xcode. Sampling logic tested in `PositionTests.swift` (AC1, AC2). `LocationRecorder.swift` uses CLLocationManager + CLBackgroundActivitySession; resume after relaunch via a per-trip flag. Not run on a phone yet.

**Depends on:** #1

## Scope

- **Interval setting:** 30 s, 1 min, 2 min, 5 min, 15 min (default chosen in #9). Settings screen
  shows an honest battery hint per option.
- **Recording:** `CLLocationUpdate.liveUpdates()` (or `CLLocationManager` with
  `allowsBackgroundLocationUpdates`) with `CLBackgroundActivitySession` while recording. Accuracy and
  `distanceFilter` derived from the interval (e.g. ≥ 5 min → hundred-metre accuracy). The app keeps
  **at most one point per interval**, preferring the most accurate one in the window.
  Standing still → no new points beyond one per 15 min (heartbeat).
- iOS doesn't run code on a timer in the background, so the interval is a target, not a guarantee.
  Points come in when location updates arrive.
- **Start/stop:** recording toggle on the trip screen; auto-off after the trip's end date + 1 day;
  optional auto-on at trip start (asks once).
- **Permissions:** When In Use first, then the "Always" upgrade explained on screen. Recording
  works with When In Use + background activity session; Always is needed only for auto-start.
- **Storage:** SwiftData `PositionPoint(recordedAt, lat, lon, accuracy, altitude, speed, tripId, sent)`.
  Points older than 30 days that were sent are pruned.
- Recording indicator: iOS blue pill + app status (#8).

## Acceptance Criteria

1. With a 1-min interval, a 30-min walk with the phone locked stores 28–31 points.
2. With a 5-min interval, a stationary hour stores ≤ 5 points.
3. Killing the app from the switcher and reopening resumes recording if it was on.
4. Denying location shows a clear explanation with a link to Settings; nothing crashes.
