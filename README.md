# Travel app

A small Django app for tracking our holidays. Live at https://trips.aquiles.me.

## Stack

- **Django** (gunicorn + WhiteNoise for static files) in the `web` container
- **Postgres 18** in the `db` container, data in the `postgres_data` volume
- **Cloudflare tunnel** for public access. The `web` container is published only on
  `127.0.0.1:8000`; the tunnel forwards `trips.aquiles.me` to it.

## First-time setup

```sh
cp .env.example .env
# Fill in DJANGO_SECRET_KEY and POSTGRES_PASSWORD, e.g.:
#   openssl rand -base64 48   (secret key)
#   openssl rand -hex 24      (db password: letters/digits only)
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Migrations and `collectstatic` run automatically every time the `web` container starts.

## Cloudflare tunnel

The machine already runs a `cloudflared` container (host networking, from the
`home_assistant` project). In the Cloudflare Zero Trust dashboard, add a public
hostname to that tunnel:

- Hostname: `trips.aquiles.me`
- Service: `http://localhost:8000`

## Deploying new code

```sh
git pull
docker compose up -d --build
```

## Useful commands

```sh
docker compose logs -f web                         # app logs
docker compose exec web python manage.py shell     # Django shell
docker compose exec db psql -U trips trips         # database shell
docker compose exec db pg_dump -U trips trips > backup.sql   # database backup
```
