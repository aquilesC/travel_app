# EPIC ios: iPhone trip app

**Status:** planned 2026-11-11. Design: [`docs/designs/ios-trip-recorder.md`](../../docs/designs/ios-trip-recorder.md).
Server side: [v4 epic](../19-epic-v4-api-tailwind.md). Inside this folder `#N` means `ios/0N`;
server issues are written `v4 #N`.

## Goal

A native SwiftUI app for two people that records position at a chosen interval and shares it
live, posts text, voice, photo and video offline-first, and makes it quick to pick the right photos
by time or place and upload the originals. Editing and cleanup stay on the website.

## Decisions

| Topic | Decision |
|---|---|
| Stack | Swift 6, SwiftUI, SwiftData, iPhone only. Minimum iOS: current major minus one |
| Repo | `ios/` in this repo, next to `api/openapi.json`; a plain `.xcodeproj` is fine |
| API client | Generated from `api/openapi.json` with Apple's `swift-openapi-generator` (build plugin). No hand-written models |
| Auth | allauth headless app token in the Keychain (v4 #22) |
| Background | Location background mode (keeps the app alive while recording) + background `URLSession` for media |
| Distribution | TestFlight internal testing; Apple Developer Program account required |
| Devices | Each phone works on its own; no device-to-device sync |
| WhatsApp | Stays available as fallback until the app has carried a real trip |

## Child issues

| # | Title | Priority | Needs server |
|---|---|---|---|
| [1](01-project-setup.md) | Project setup, generated API client, TestFlight | Critical | v4 #21 |
| [2](02-login-trip-picker.md) | Login and trip picker | Critical | v4 #22, #23 |
| [3](03-location-recording.md) | Location recording at a user-set interval | Critical | — |
| [4](04-position-upload.md) | Batched position upload (live sharing) | Critical | v4 #26, #27 |
| [5](05-outbox.md) | Offline outbox and resumable uploads | Critical | v4 #25 |
| [6](06-compose.md) | Compose: text, photo, video, voice note | High | v4 #24 |
| [7](07-photo-picker.md) | Photo picker with time and map filters | High | v4 #25, #28 |
| [8](08-status-settings.md) | Trip status screen and settings | Medium | — |
| [9](09-field-test.md) | Weekend field test and battery tuning | Critical | all |

### Milestones

1. **Live location** (#1–#4, #8 basic): family can follow a trip. First usable build.
2. **Posting from the phone** (#5, #6): Twilio becomes optional.
3. **Photo picking** (#7).
4. **Field test** (#9), then decide on the Twilio question.
