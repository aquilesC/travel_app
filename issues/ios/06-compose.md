# ios #6: Compose: text, photo, video, voice note

**Status:** code written 2026-11-11, not yet built in Xcode. Compose screen: text, place (reverse geocoded), photos/videos from the library, voice note, new chapter. Deviation: no in-app camera; take the photo with the Camera app and pick it. Post flow tested end-to-end in TripsKit.

**Depends on:** #5, v4 #24

The in-app replacement for posting through WhatsApp.

## Scope

- Compose screen reachable in one tap from the trip screen (and a Home Screen quick action).
- **Text:** markdown textarea, place name (prefilled by reverse geocoding the current position,
  editable), public/private toggle (default public, like the web editor).
- **Photo/video:** take with the camera or pick from the library (`PhotosPicker`); several per post.
  Originals are uploaded (HEIC / HEVC as they are); the server makes web versions.
- **Voice note:** record with `AVAudioRecorder` (AAC `.m4a`), waveform + play back before sending,
  max 10 min.
- **Chapter:** shows the trip's current chapter; "New chapter…" sets a new current chapter (like WhatsApp `#chapter`).
- Entry gets `occurred_at` = when you tapped Send, plus the current position.
- Submit goes to the outbox (#5); the post appears immediately in a local "Sent / sending" list.

## Acceptance Criteria

1. Text-only post offline → appears on the website within a minute of reconnecting, with the right
   local time and location.
2. A post with 3 photos, 1 video and a voice note arrives as one entry with all 5 media in order.
3. A private post never shows on the share page.
4. Starting a new chapter from the app makes later WhatsApp and app posts go into it.
