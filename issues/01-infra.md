# v1 #1: Infra

**Status:** implemented 2026-11-09, tests in `trips/tests/` (`accounts/tests.py` for #2), verified on the live stack.

Part of epic [00-epic-v1-travel-journal.md](00-epic-v1-travel-journal.md): v1 travel journal for Sri Lanka (departure 2026-12-21). Data model, locked decisions and timeline live in the epic.

**Depends on (epic child numbers):** —

## Scope

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

## Acceptance Criteria (numbering from the epic)

1. `docker compose up -d --build` from a clean checkout with `.env` starts `db`, `web`, `nginx`,
   `worker`, `scheduler`; `https://trips.aquiles.me/healthz/` returns 200.
12. `nightly_backup` produces a dump that restores into an empty database with `pg_restore`, and
    only the newest 14 dumps remain.
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
