# v1 #4: Media

**Status:** implemented 2026-11-09, tests in `trips/tests/` (`accounts/tests.py` for #2), verified on the live stack.

Part of epic [00-epic-v1-travel-journal.md](00-epic-v1-travel-journal.md): v1 travel journal for Sri Lanka (departure 2026-12-21). Data model, locked decisions and timeline live in the epic.

**Depends on (epic child numbers):** #1, #3

## Scope

- Chunked upload endpoint: `POST /media/upload/` (init → chunks ≤ 50 MB → complete), vanilla JS,
  resumable per chunk, sha256 verified on complete; files written to `originals/<trip_id>/`.
- Duplicate sha256 within the same entry rejected with a message.
- Tasks: `process_photo` (Pillow + `pillow-heif`: EXIF orientation, taken_at, GPS; WebP sm 400px,
  md 1200px, lg 2400px), `process_video` (ffmpeg H.264/AAC max 720p, faststart; poster at 1 s;
  duration), `process_audio` (keep original; AAC m4a copy if not mp3/m4a). Status → ready/failed
  with error text; "retry" button for failed.
- Entry editor: add/remove/reorder media, set trip cover, badge "travel copy" on
  `is_travel_copy` items.

## Acceptance Criteria (numbering from the epic)

3. A 300 MB video uploaded through `trips.aquiles.me` succeeds (chunked), keeps a byte-identical
   original (sha256 matches), and gets a playable 720p MP4 + poster within 10 min.
4. An iPhone HEIC photo gets sm/md/lg WebP derivatives with correct orientation and its EXIF
   `taken_at` and GPS stored.
- Each test states its card: `protects=<observable it protects>; fails_when=<wrong result it rejects>; no_claim=<what green does not prove>`
- No degradation of existing functionality (`/healthz/`, admin).

## Rules for the implementing agent

1. Acceptance criteria are the `protects / fails_when / no_claim` profile of each test: the observable it protects, the wrong result it rejects, and what green does not prove. Never "make the tests pass".
2. Real code and real tests land in the same change; a placeholder, a stub assertion or a test deferred to a follow-up is not done.
3. Any change to a test, validator, CI step, timeout, tolerance, threshold, snapshot or suppression pragma is reported on its own line in your summary with its justification, before any other result.
4. A reported command names the command and its observed result (exit status, counts, the failing line); a command you did not run is not reported, and stderr is never silenced in a command you cite.
5. Your report is a claim until the parent re-executes it: say what you verified, what you reused, and what you could not check.

## Rollback

Revert the PR; v1 migrations are additive (`migrate <app> <previous>` before reverting code).
