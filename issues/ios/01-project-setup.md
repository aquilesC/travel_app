# ios #1: Project setup, generated API client, TestFlight

**Status:** code written 2026-11-11, not yet built in Xcode. TripsKit package + generated client build and test on Linux (`ios/test.sh`). XcodeGen `project.yml` instead of a committed .xcodeproj. Not yet built in Xcode or on TestFlight: needs a Mac and the developer account.

**Depends on:** v4 #21 (OpenAPI file exists)

## Scope

- **User action first:** enrol in the Apple Developer Program (identity check can take days);
  create the App ID with capabilities: Background Modes (location, background fetch).
- Xcode project in `ios/TripsApp/`, SwiftUI app, Swift 6 strict concurrency, SwiftData container.
- `swift-openapi-generator` build plugin reading `../../api/openapi.json` (symlink or copy step);
  `swift-openapi-urlsession` transport; middleware adding `X-Session-Token` and a `User-Agent`
  with app version.
- Build configurations: `Debug` → configurable base URL (local Docker via LAN IP),
  `Release` → `https://trips.aquiles.me`.
- `Info.plist` usage strings: location (When In Use + Always), photo library, camera, microphone.
- `ios/README.md`: open, run on device, archive, upload to TestFlight, add the second tester.
- Basic logging with `os.Logger` categories (location, upload, api).

## Acceptance Criteria

1. A build installs on both phones via TestFlight.
2. The app calls `GET /api/v1/health` with the generated client and shows the API version.
3. Changing `api/openapi.json` and rebuilding regenerates the client (no hand-edited API code).
