# Trips for iPhone

A SwiftUI app for the two of us: records where we go and shares it live, posts text, voice,
photos and video offline-first, and makes it quick to pick the photos for the journal.
Editing stays on the website. Issues: [`issues/ios/`](../issues/ios/00-epic-ios-app.md).

## Layout

| Path | What | Builds on |
|---|---|---|
| `TripsKit/` | Swift package: the API client generated from [`api/openapi.json`](../api/openapi.json) (`TripsAPI`) and all logic that doesn't need Apple-only frameworks (`TripsKit`): position sampling, the on-disk position store and batch uploader, the outbox with resumable chunked uploads, trip calendar, photo filters | Linux and Apple |
| `TripsApp/` | The app: SwiftUI screens, CoreLocation, PhotoKit, voice notes, Keychain, background tasks | Xcode only |
| `project.yml` | XcodeGen spec for `Trips.xcodeproj` (the project file isn't committed) | |

The API client is generated at build time from the contract file, so a server change that
updates `api/openapi.json` shows up in Swift as compile errors, not runtime surprises.

## Run it on your iPhone

1. Join the Apple Developer Program (developer.apple.com, $99/yr; identity check can take days).
2. On a Mac with Xcode 26+: `brew install xcodegen`.
3. `cp ios/Local.xcconfig.example ios/Local.xcconfig` and put your team id in it
   (developer.apple.com › Account › Membership).
4. `cd ios && xcodegen && open Trips.xcodeproj`, pick your iPhone, Run.
5. TestFlight for both phones: Product › Archive › Distribute App › TestFlight (internal testing),
   then add the second Apple ID as an internal tester in App Store Connect.

Debug builds talk to `https://trips.aquiles.me` by default. To use a dev server on the LAN, set
the server URL under Settings › Developer and restart the app.

## Tests

TripsKit is tested without a Mac, in the official Swift image:

```sh
ios/test.sh            # unit tests (sampler, uploader, outbox, filters, dates)
ios/test.sh e2e        # the generated client against a running dev website (never production)
```

`e2e` expects the isolated dev stack (`trips-dev-web` on the `trips-dev` Docker network) with a
user `dev@example.com` / `dev-pass-123` and a trip that includes today; override with
`TRIPS_E2E_URL`, `TRIPS_E2E_EMAIL`, `TRIPS_E2E_PASSWORD`. On a Mac, `swift test` in `TripsKit/` works too.

The app target (`TripsApp/`) has no automated tests yet; its behaviour is checked on the phone
in the field test (ios #9).

## How it behaves

- **Location:** one point per chosen interval (30 s – 15 min), the most accurate fix in each
  window; standing still keeps one point per 15 min. Points are saved on the phone first and sent
  in batches at the chosen upload interval, over mobile data too (they're tiny). iOS doesn't run
  apps on a timer in the background, so "every N minutes" means "when a location update arrives
  and N minutes have passed".
- **Outbox:** posts and photo imports are saved on the phone at once and sent in order. Uploads go
  in 50 MB chunks and resume where they stopped. Files over 20 MB wait for wifi unless you tap
  "Send now anyway". Every create carries a client id, so a retry never duplicates a post.
- **Photos:** only the photos you pick are uploaded, as originals. The website groups them into
  draft entries and places photos without GPS using your recorded path.
