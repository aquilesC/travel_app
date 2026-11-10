# Travel app

A small Django app for tracking our holidays. Live at https://trips.aquiles.me.
Specs for the work live in [`issues/`](issues/).

## Stack

| Container | Role |
|---|---|
| `nginx` | Front door on `127.0.0.1:8000`; proxies to Django and serves media after Django authorises it (`X-Accel-Redirect`) |
| `web` | Django + gunicorn. Runs migrations and `collectstatic` on start |
| `worker` | Background tasks (`db_worker`): media processing, WhatsApp messages, emails, backups |
| `scheduler` | Enqueues the nightly backup (03:00) and the daily digest (20:00), Amsterdam time |
| `db` | Postgres 18, data in the `postgres_data` volume (internal disk) |

Media (originals, derived versions, database dumps) live in the `media` volume.
The Cloudflare tunnel (`cloudflared` from the `home_assistant` project) sends
`trips.aquiles.me` to `http://localhost:8000`.

## First-time setup

```sh
cp .env.example .env
# Fill in DJANGO_SECRET_KEY and POSTGRES_PASSWORD, e.g.:
#   openssl rand -base64 48   (secret key)
#   openssl rand -hex 24      (db password: letters/digits only)
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Then in the admin (`/admin/` → Users), set each person's **WhatsApp number**
(international format, e.g. `+316…`). Only these numbers can post.

## Deploying new code

```sh
git pull
docker compose up -d --build
```

## Tests

```sh
docker compose run --rm --no-deps -v "$PWD":/app -e RUN_MIGRATIONS=0 web python manage.py test accounts trips
```

## Importing

- **Photos into a trip:** trip page → "+ Photos". Upload many at once; on the review page you can
  shift a camera's clock. Photos are grouped into entries (new entry after 60 min or 2 km).
- **New trip from photos:** home → "New trip from photos". Same flow; the trip's dates and time zone
  come from the photos, and optional GPX tracks help place photos without GPS.
- **New trip from GPX:** home → "New trip from GPX". Each file becomes a track; dates come from the
  timestamps.

Photos without GPS get a location from a GPX track covering their time (±10 min), otherwise
between the nearest located photos (within 6 h). The entry editor marks such locations.

## Accounts

- `/account/`: name, email, profile picture, WhatsApp number, public-profile switch.
- `/u/<username>/`: public profile with trip count, km travelled and shared trips.

## WhatsApp (Twilio)

1. Twilio console → Messaging → WhatsApp sender (or the sandbox while testing).
2. "When a message comes in": `https://trips.aquiles.me/hooks/twilio/whatsapp/`, HTTP POST.
3. Fill `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` in `.env`, then
   `docker compose up -d`.

Messages go to the trip whose dates include today (in the trip's time zone).
Messages within 10 minutes of each other become one entry. Commands, on the first line:

| Command | Effect |
|---|---|
| `#chapter Galle` | Starts chapter "Galle"; later messages go into it |
| `#new` | Starts a new entry even within 10 minutes |
| `#private` | Hides the current entry from the share link and emails |

Shared locations become check-ins. Photos/videos arrive as reduced-quality "travel
copies" (WhatsApp limits: 16 MB, 5 MB per image); upload originals later in the entry editor.

## Email (Mailgun)

Fill the `EMAIL_*` and `DEFAULT_FROM_EMAIL` values in `.env`. Without `EMAIL_HOST`,
emails are printed to the `worker` logs instead of sent.

## Moving media to the external drive

```sh
docker compose down
sudo mkdir -p /mnt/trips-media && sudo chown 1000:1000 /mnt/trips-media
sudo rsync -a /var/lib/docker/volumes/travel_app_media/_data/ /mnt/trips-media/
# in .env:
#   COMPOSE_FILE=compose.yaml:compose.hd.yaml
#   MEDIA_HOST_PATH=/mnt/trips-media
docker compose up -d
```

Make sure the drive is mounted at boot (`/etc/fstab`) before Docker starts.

## Backups

- Nightly at 03:00 a `pg_dump` goes to `backups/` on the media volume; the newest 14 are kept.
- Off-site: back up the media folder with restic to Backblaze B2 (run on the host):

```sh
export B2_ACCOUNT_ID=… B2_ACCOUNT_KEY=… RESTIC_PASSWORD=…
restic -r b2:<bucket>:trips init                       # once
restic -r b2:<bucket>:trips backup /mnt/trips-media    # e.g. nightly via cron at 04:00
```

Restore the database from a dump:

```sh
docker compose exec -T db pg_restore -U trips -d trips --clean --if-exists < backups/trips-YYYYMMDD-HHMMSS.dump
```

## Useful commands

```sh
docker compose logs -f web worker          # app and task logs
docker compose exec web python manage.py shell
docker compose exec db psql -U trips trips
```
