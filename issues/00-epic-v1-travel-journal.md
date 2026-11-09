# EPIC: v1 travel journal, ready for Sri Lanka (departure 2026-12-21)

**Status:** children 01–08 implemented 2026-11-09. Remaining before departure: Twilio sender approval + `.env` credentials, Mailgun credentials, field-test weekend 2026-12-12/13.

## Context

The two users (Aquiles and wife) want a private, long-lived travel journal: trips recorded as they happen
(WhatsApp messages from the phone) and edited afterwards on a big screen, with photos, video,
audio, text, check-ins, GPX tracks and maps, shared with family through a link and a daily email
digest. Today everything lives in Apple Photos: camera photos lack locations, GPX tracks have no
home, and there is no way to journal on the road. The first real use is the Sri Lanka trip
departing **2026-12-21**; the long-term goal is a browsable archive of every trip, eventually
printable as a book.

## Current State (verified 2026-11-09, commit `cb7c5da`)

| Component | State |
|---|---|
| `config/settings.py` | Env-driven settings, Postgres via `DATABASE_URL`, WhiteNoise static, `SECURE_PROXY_SSL_HEADER` for Cloudflare, console email backend (`MAILERS`) |
| `config/urls.py` | Only `admin/` and `healthz/` |
| `compose.yaml` | Services `db` (postgres:18-alpine, volume `postgres_data`) and `web` (gunicorn, `127.0.0.1:8000`, volume `media` → `/app/media`). No worker, no scheduler |
| Django apps | None (only contrib apps) |
| Host | 98 GB system disk (69 GB free), 8 cores, 7 GB RAM (+16 GB planned), external 8 TB HD to be attached later |
| Public access | `trips.aquiles.me` → existing `cloudflared` (host network, `home_assistant` project) → `http://localhost:8000`. Cloudflare free plan: 100 MB max request body |

## Decisions (locked in conversation)

| Topic | Decision |
|---|---|
| App split | Two apps: `accounts` (auth, profiles) and `trips` (everything else). No further splitting in v1 |
| Frontend | Server-rendered Django templates, minimal vanilla JS. Only JS library: MapLibre GL JS (maps), with OpenFreeMap tiles (no API key). No HTMX, no SPA |
| API | None in v1. A JSON API for a companion app is a later epic; web frontend and app evolve independently |
| Background jobs | Django Tasks API (`django.tasks`) with the `django-tasks` database backend, one `worker` container. No Celery/Redis |
| Scheduling | A `scheduler` container running `manage.py run_scheduler` (simple loop) that enqueues periodic tasks |
| Storage | Docker named volumes. `media` volume becomes a bind-type local volume pointing at `${MEDIA_HOST_PATH}` once the 8 TB HD is attached; default Docker location until then. Postgres data stays on the internal SSD |
| Backups | Nightly `pg_dump` into the media volume (`/app/media/backups/`), retention 14 dumps. Off-site: restic → Backblaze B2 of the media path (documented in README, run on host, outside the app) |
| GPX | Stored verbatim as text (`Track.gpx_text`), parsed with `gpxpy` at render time; parsed/simplified GeoJSON cached in Django's cache, never persisted as source of truth |
| PostGIS | Not used. Plain decimal lat/lon |
| WhatsApp | Twilio WhatsApp. Only the two users' numbers accepted. Twilio sandbox for development; production sender registration started immediately (Meta approval lead time) |
| WhatsApp media | 16 MB/message, 5 MB/image limit → WhatsApp media is a **travel copy**. Full-resolution originals added manually via the web editor; no automatic matching in v1 |
| Email | Mailgun via Django's SMTP backend (no extra library). Daily digest per trip, double opt-in, one-click unsubscribe |
| Sharing | One unguessable share link per trip (`/s/<token>/`), anonymous. Per-entry `is_public` flag; private entries and their media never reachable via the link |
| Text | Markdown in a plain textarea, rendered server-side with `markdown` + `nh3` sanitising |
| Time zones | One IANA time zone per trip (e.g. `Asia/Colombo`); all trip times shown in it. Multi-timezone trips out of scope |
| Video | Originals kept untouched; worker produces H.264/AAC 720p MP4 + poster JPEG with ffmpeg |
| Large uploads | Web uploads use vanilla-JS chunked upload (≤ 50 MB chunks) to pass Cloudflare's 100 MB limit |
| Tests | Django's built-in test runner (`manage.py test`) |

## Data model (`trips` app unless noted)

```python
# accounts
class Profile(Model):
    user = OneToOneField(User, on_delete=CASCADE)
    whatsapp_number = CharField(max_length=20, unique=True, null=True)   # E.164 format: "+" country code + number

# trips
class Person(Model):                       # travel companions (not app users)
    name = CharField(max_length=100, unique=True)

class Trip(Model):
    title = CharField(max_length=200)
    start_date = DateField()
    end_date = DateField()                 # CheckConstraint end_date >= start_date
    timezone = CharField(max_length=64, default="Europe/Amsterdam")   # validated against zoneinfo
    description = TextField(blank=True)    # markdown
    companions = ManyToManyField(Person, blank=True)
    cover = ForeignKey("Media", null=True, blank=True, on_delete=SET_NULL, related_name="+")
    share_token = CharField(max_length=32, unique=True, default=secrets.token_urlsafe(16))
    share_enabled = BooleanField(default=True)
    created_by = ForeignKey(User, on_delete=PROTECT)
    created_at / updated_at

class Chapter(Model):
    trip = ForeignKey(Trip, on_delete=CASCADE, related_name="chapters")
    title = CharField(max_length=200)
    position = PositiveIntegerField()      # unique (trip, position)
    created_at

class Entry(Model):
    trip = ForeignKey(Trip, on_delete=CASCADE, related_name="entries")
    chapter = ForeignKey(Chapter, null=True, blank=True, on_delete=SET_NULL)
    author = ForeignKey(User, on_delete=PROTECT)
    occurred_at = DateTimeField(db_index=True)          # stored UTC
    body = TextField(blank=True)                        # markdown
    place_name = CharField(max_length=200, blank=True)
    latitude = DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_public = BooleanField(default=True)
    source = CharField(choices=[("web","web"),("whatsapp","whatsapp")])
    created_at / updated_at
    # An entry with lat/lon is a check-in point; the trip path = tracks + entry points ordered by time.

class Media(Model):
    entry = ForeignKey(Entry, on_delete=CASCADE, related_name="media")
    kind = CharField(choices=photo/video/audio)
    original = FileField(upload_to="originals/<trip_id>/<uuid4><ext>")   # never modified
    is_travel_copy = BooleanField(default=False)        # True for WhatsApp-sourced files
    status = CharField(choices=pending/ready/failed, default="pending")
    error = TextField(blank=True)
    derivatives = JSONField(default=dict)   # {"sm": path, "md": path, "lg": path} | {"mp4": path, "poster": path} | {"audio": path}
    sha256 = CharField(max_length=64, db_index=True)
    size_bytes = BigIntegerField()
    taken_at = DateTimeField(null=True)     # from EXIF/metadata
    latitude / longitude                    # from EXIF, nullable
    width / height / duration_seconds       # nullable
    position = PositiveIntegerField(default=0)
    created_at

class Track(Model):
    trip = ForeignKey(Trip, on_delete=CASCADE, related_name="tracks")
    chapter = ForeignKey(Chapter, null=True, blank=True, on_delete=SET_NULL)
    name = CharField(max_length=200, blank=True)
    mode = CharField(choices=sail/bike/hike/walk/car/transit/other)
    gpx_text = TextField()                  # verbatim upload, source of truth
    uploaded_by = ForeignKey(User, on_delete=PROTECT)
    created_at

class Subscriber(Model):
    trip = ForeignKey(Trip, on_delete=CASCADE, related_name="subscribers")
    email = EmailField()                    # unique (trip, email)
    token = CharField(max_length=32, unique=True)       # confirm + unsubscribe
    confirmed_at = DateTimeField(null=True)
    unsubscribed_at = DateTimeField(null=True)
    last_digest_at = DateTimeField(null=True)
    created_at

class InboundMessage(Model):                # raw Twilio webhook log, idempotency + no data loss
    message_sid = CharField(max_length=64, unique=True)
    from_number = CharField(max_length=20)
    payload = JSONField()                   # full POST body
    status = CharField(choices=received/processed/unrouted/rejected/failed)
    entry = ForeignKey(Entry, null=True, on_delete=SET_NULL)
    error = TextField(blank=True)
    received_at = DateTimeField(auto_now_add=True)
```

## Child Issues

| # | Title | Priority | Effort (human / CC) | Dependencies |
|---|---|---|---|---|
| [1](01-infra.md) | Infra: worker, scheduler, media volume, nightly pg_dump, protected media serving | Critical | 2d / 1h | — |
| [2](02-accounts.md) | Accounts: login/logout, Profile with WhatsApp number | Critical | 0.5d / 20m | — |
| [3](03-trips-core.md) | Trips core: models, admin, web editor for trips/chapters/entries | Critical | 3d / 2h | 2 |
| [4](04-media.md) | Media: chunked upload, processing (photo/HEIC, video, audio), gallery | Critical | 3d / 2h | 1, 3 |
| [5](05-tracks-and-map.md) | Tracks & map: GPX upload, render-time parsing, trip map | High | 2d / 1h | 3 |
| [6](06-share-page.md) | Public share page | High | 1d / 45m | 4, 5 |
| [7](07-whatsapp-ingest.md) | WhatsApp ingest via Twilio | Critical | 3d / 2h | 1, 3, 4 |
| [8](08-digest.md) | Subscriptions & daily digest via Mailgun | Medium | 1.5d / 1h | 1, 6 |

### Dependency Graph

```
#2 Accounts ──> #3 Trips core ─┬─> #4 Media ──┬─> #6 Share page ──> #8 Digest
#1 Infra ──────────────────────┤              │
                               ├─> #5 Tracks ─┘
                               └─> #7 WhatsApp ingest (also needs #1, #4)
```

### Sequencing Rationale

\#1–#3 are the substrate: nothing can be stored or processed without them. #4 before #7 because
WhatsApp ingest reuses the media pipeline. #7 is Critical because it is the only way to post while
travelling, and needs real-device testing on a weekend before departure. #8 is last because family
can use the share link without it; if time runs out, #8 slips to the trip's first week.

### Timeline

| Date | Milestone |
|---|---|
| 2026-11-10 | Start Twilio WhatsApp sender registration (Meta business verification) — **user action** |
| 2026-11-23 | #1–#4 merged |
| 2026-12-07 | #5–#7 merged |
| 2026-12-12/13 | Field test: post a full weekend via WhatsApp |
| 2026-12-14 | #8 merged, code freeze; only fixes after this |
| 2026-12-21 | Departure |

---

### #1 Infra

- Add `django-tasks` (DB backend) to `requirements.txt`, `INSTALLED_APPS`, `TASKS` setting.
- `compose.yaml`: services `worker` (same image, `python manage.py db_worker`) and `scheduler`
  (`python manage.py run_scheduler`), both `depends_on: db healthy`, sharing the `media` volume.
  Only `web` runs migrations (entrypoint); worker/scheduler skip migrate/collectstatic via env flag.
- `media` volume: `driver_opts {type: none, o: bind, device: ${MEDIA_HOST_PATH}}` when
  `MEDIA_HOST_PATH` is set; document the switch-over procedure (stop, rsync, change env, start).
- `run_scheduler` management command: loop every 60 s, enqueue `nightly_backup` at 03:00
  Europe/Amsterdam and `send_daily_digests` at 20:00 Europe/Amsterdam, at most once per day
  (state stored in a `ScheduledRun(name, last_run_date)` table to survive restarts).
- `nightly_backup` task: `pg_dump -Fc` to `/app/media/backups/trips-YYYYMMDD.dump`, keep newest 14.
  Image gets `postgresql-client` matching server major version (18).
- Protected media: add `nginx` service in front of `web` (nginx publishes `127.0.0.1:8000`).
  nginx proxies everything to gunicorn; `/media/` is `internal` and only served via Django's
  `X-Accel-Redirect` after a permission check. `client_max_body_size 60m`.
- ffmpeg installed in the image (`apt-get install ffmpeg`).
- README: restic → B2 backup of `${MEDIA_HOST_PATH}` (commands, not automated by the app).

### #2 Accounts

- App `accounts`: `Profile` model (above), created by signal on user creation; admin inline.
- Django auth views at `/accounts/login/`, `/accounts/logout/`; `LOGIN_URL`, `LOGIN_REDIRECT_URL="/"`.
- All non-public views require login. No self-signup; users created via `createsuperuser`/admin.

### #3 Trips core

- Models `Person`, `Trip`, `Chapter`, `Entry` with migrations and admin.
- Web UI (login required), base template, mobile-first CSS (no framework):
  - `/` trip list (newest first), "new trip".
  - `/trips/<id>/` timeline: entries grouped by chapter, ordered by `occurred_at`, times in trip TZ;
    filter "public only / all".
  - Create/edit/delete forms for trip, chapter (incl. reorder by position), entry (body markdown
    with preview, occurred_at in trip TZ, place name, lat/lon, is_public, chapter).
- Markdown rendering via `markdown` + `nh3` allowlist sanitising.

### #4 Media

- Chunked upload endpoint: `POST /media/upload/` (init → chunks ≤ 50 MB → complete), vanilla JS,
  resumable per chunk, sha256 verified on complete; files written to `originals/<trip_id>/`.
- Duplicate sha256 within the same entry rejected with a message.
- Tasks: `process_photo` (Pillow + `pillow-heif`: EXIF orientation, taken_at, GPS; WebP sm 400px,
  md 1200px, lg 2400px), `process_video` (ffmpeg H.264/AAC max 720p, faststart; poster at 1 s;
  duration), `process_audio` (keep original; AAC m4a copy if not mp3/m4a). Status → ready/failed
  with error text; "retry" button for failed.
- Entry editor: add/remove/reorder media, set trip cover, badge "travel copy" on
  `is_travel_copy` items.

### #5 Tracks & map

- Upload GPX (file input; ≤ 50 MB) into `Track.gpx_text`, with mode/name/chapter. Reject files
  `gpxpy` can't parse, with the parser error.
- `track_geojson(track)`: parse with `gpxpy`, simplify (Ramer–Douglas–Peucker, ~10 m tolerance),
  return GeoJSON LineString + stats (distance km, duration, elevation gain). Cached in Django
  cache (key `track:<id>:<updated_at>`); `CACHES` uses the database cache backend.
- Trip map (MapLibre + OpenFreeMap "liberty" style): tracks coloured by mode, entry check-in
  points with popups linking to the entry, fit bounds to all features. Rendered on the trip page.

### #6 Public share page

- `/s/<share_token>/`: read-only trip page (title, dates, companions, chapters, public entries,
  map with tracks and public entry points). 404 if token unknown or `share_enabled=False`.
- Media requests from the share page authorised by token + `entry.is_public`; private entry media
  returns 404 even with a guessed path.
- `<meta name="robots" content="noindex">`; owner can regenerate the token (old link dies).
- "Subscribe to updates" form (wired in #8).

### #7 WhatsApp ingest (Twilio)

- `POST /hooks/twilio/whatsapp/`: validate `X-Twilio-Signature` (reject 403), store
  `InboundMessage` (idempotent on `MessageSid`), return 200 fast, enqueue `process_inbound(id)`.
- Sender allowlist: `From` must match a `Profile.whatsapp_number`, else `rejected`, no reply.
- Routing: trip with `start_date ≤ today (trip TZ) ≤ end_date`; if several, latest `start_date`.
  None → `unrouted`, reply "No active trip; saved, assign it on the web" (unrouted messages listed
  in the UI and assignable to a trip).
- Grouping: append to the sender's latest `whatsapp` entry in that trip if it was created
  ≤ 10 min ago and the message isn't `#new`; else create a new entry (`occurred_at` = receive time).
- Content: text → appended to body; `MediaUrl*` → downloaded with Twilio basic auth into
  `Media(is_travel_copy=True)` and processed via #4; WhatsApp location (`Latitude`/`Longitude`,
  optional `Address`/`Label`) → sets entry lat/lon/place_name (new entry if current one already
  has a location); voice note → audio media.
- Commands (first token of body): `#chapter <title>` creates a chapter and makes it current for
  the trip; `#new` forces a new entry; `#private` sets `is_public=False` on the current entry.
- Reply (within 24 h service window, free of Meta fees): "Added to <trip> (<edit url>)", one reply
  per entry, not per message.
- Settings: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`.

### #8 Subscriptions & daily digest

- Mailgun SMTP via Django SMTP backend in `MAILERS` (env `EMAIL_HOST/PORT/USER/PASSWORD`,
  `DEFAULT_FROM_EMAIL` = a `trips` mailbox on the aquiles.me domain, set in `.env`). Console backend when `DJANGO_DEBUG=true`.
- Subscribe form on share page → `Subscriber` + confirmation email; unconfirmed rows expire after
  7 days. Every email has a one-click unsubscribe link and `List-Unsubscribe` header.
- `send_daily_digests` task (20:00 Europe/Amsterdam): per confirmed subscriber, public entries
  created since `last_digest_at` (or confirmation); skip if none; HTML + text email with entry
  text excerpt, up to 6 thumbnails, link to share page. Updates `last_digest_at` after send.

## Acceptance Criteria

1. `docker compose up -d --build` from a clean checkout with `.env` starts `db`, `web`, `nginx`,
   `worker`, `scheduler`; `https://trips.aquiles.me/healthz/` returns 200.
2. Anonymous request to any page except `/s/<token>/…`, `/healthz/`, `/accounts/login/`,
   `/hooks/twilio/…` and subscribe/confirm/unsubscribe URLs redirects to login.
2b. An entry time entered as 18:00 in a trip with time zone `Asia/Colombo` is stored as 12:30 UTC
   and displayed as 18:00; a trip with `end_date` before `start_date` is rejected; a `<script>`
   tag in entry markdown is stripped from the rendered HTML.
3. A 300 MB video uploaded through `trips.aquiles.me` succeeds (chunked), keeps a byte-identical
   original (sha256 matches), and gets a playable 720p MP4 + poster within 10 min.
4. An iPhone HEIC photo gets sm/md/lg WebP derivatives with correct orientation and its EXIF
   `taken_at` and GPS stored.
5. A 100k-point GPX renders on the trip map in under 3 s on first view and under 300 ms when
   cached; the stored `gpx_text` is byte-identical to the upload.
6. Share link shows public entries only; fetching a private entry's media URL with the share
   token returns 404; disabling sharing makes the link 404.
7. Twilio webhook with an invalid signature returns 403 and stores nothing; a replayed
   `MessageSid` creates no duplicate entry.
8. Message from a number not in a Profile creates no entry and sends no reply.
9. Sending 5 photos + a caption within 2 minutes produces exactly one entry with 5 media items and
   one reply; `#new` then a text produces a second entry; `#chapter Galle` creates chapter "Galle"
   and later entries attach to it.
10. A message on a date with no active trip is stored as `unrouted` and can be assigned on the web.
11. Digest: a confirmed subscriber gets exactly one email per day with new public entries, none on
    days without entries, none after unsubscribing; unconfirmed subscribers get none.
12. `nightly_backup` produces a dump that restores into an empty database with `pg_restore`, and
    only the newest 14 dumps remain.
13. Each test in the Testing Plan states its card: `protects=<observable it protects>;
    fails_when=<wrong result it rejects>; no_claim=<what green does not prove>`.
14. No degradation of existing functionality (`/healthz/`, admin).

## Testing Plan

| Layer | What | Count |
|---|---|---|
| Unit | Markdown sanitising, trip routing by date/TZ, grouping window, command parsing, GPX parse/simplify, digest selection, backup retention | +20 |
| Integration | Twilio webhook (signature, idempotency, allowlist, media download mocked), chunked upload → processing (real Pillow/ffmpeg on fixture files), share-page permissions, subscribe/confirm/unsubscribe | +15 |
| E2E (manual) | Field-test weekend 2026-12-12/13: post via WhatsApp from both phones, upload GPX, share link to one family member, receive digest | 1 checklist |

## Rules for the implementing agent

1. Acceptance criteria are the `protects / fails_when / no_claim` profile of each test: the observable it protects, the wrong result it rejects, and what green does not prove. Never "make the tests pass".
2. Real code and real tests land in the same change; a placeholder, a stub assertion or a test deferred to a follow-up is not done.
3. Any change to a test, validator, CI step, timeout, tolerance, threshold, snapshot or suppression pragma is reported on its own line in your summary with its justification, before any other result.
4. A reported command names the command and its observed result (exit status, counts, the failing line); a command you did not run is not reported, and stderr is never silenced in a command you cite.
5. Your report is a claim until the parent re-executes it: say what you verified, what you reused, and what you could not check.

## Rollback Plan

- Each child issue is its own PR; revert the PR. Migrations are additive in v1; reverting a
  migration = `migrate trips <previous>` before reverting code.
- Data safety: originals and `gpx_text` are never modified, so derivatives/caches can always be
  regenerated. Nightly dumps (14 days) + restic/B2 off-site cover DB loss.
- WhatsApp: disabling the Twilio webhook URL stops ingest; `InboundMessage` keeps raw payloads
  for reprocessing.

## Effort Estimate

~16 human-days / ~10 h CC total (per child above). Critical path: #2 → #3 → #4 → #7.

## Out of Scope (later epics)

- Automatic placement of camera photos by time proximity to phone photos / GPX
- Building past trips from Apple Photos
- Companion app and JSON API; background location tracking
- WhatsApp notifications to family (paid Meta templates)
- Book/print layout (WeasyPrint)
- Logged-in friends / visibility levels beyond public/private
- Multi-timezone trips, PostGIS, persisted parsed track data
- Telegram (rejected)

## Related

- Foundation: commit `cb7c5da`
