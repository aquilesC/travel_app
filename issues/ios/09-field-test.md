# ios #9: Weekend field test and battery tuning

**Status:** planned

**Depends on:** #1–#8, v4 #20–#28

## Scope

- TestFlight build on both phones; one weekend trip (two days, at least one area with bad signal).
- Day 1: 1-min recording / 15-min upload. Day 2: 5-min / 30-min. Record battery % at 08:00, 13:00, 20:00.
- Post at least 10 entries from the app (text, voice, photo, video), none via WhatsApp.
- Evening: pick photos with the filters, upload, review drafts on the website.
- Family member checks the share page live view during the day.
- Write findings into this issue: battery numbers, gaps in the path, upload failures, UX snags.
- Set default intervals from the numbers; file follow-up issues.
- Decide (and note in the v4 epic) whether WhatsApp/Twilio stays, becomes a fallback, or goes.

## Acceptance Criteria

1. Success criteria from the design doc met, or each miss has a follow-up issue.
2. Defaults updated in the app and documented in `ios/README.md`.
3. The Twilio decision is recorded.
