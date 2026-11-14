# Trips API (`/api/v1/`)

Used by the website's own JavaScript and by the iPhone app (`ios/`). The contract is
[`openapi.json`](openapi.json): regenerate it with
`python manage.py export_openapi --output api/openapi.json` whenever an endpoint changes (a test
fails until you do). Staff can browse it at `/api/v1/docs`.

## Auth

| Caller | How | CSRF |
|---|---|---|
| Website JS | Django session cookie | Required on POST/PUT/PATCH/DELETE (`X-CSRFToken` header) |
| iPhone app | `X-Session-Token: <token>` from `POST /_allauth/app/v1/auth/login` (`{"email", "password"}` → `meta.session_token`) | Not needed |

Log out with `DELETE /_allauth/app/v1/auth/session`. Signed-in devices are listed (and can be
signed out) at `/accounts/sessions/`. There is no signup: accounts come from invites.

## Conventions

- JSON in and out. Timestamps are ISO 8601 in UTC (`2026-12-23T08:00:00Z`); dates are `YYYY-MM-DD`
  in the trip's time zone.
- **Errors** always look like
  `{"error": {"code": "not_found", "message": "…", "fields": {"title": ["…"]}}}`.
  Codes: `unauthenticated` 401, `forbidden` 403, `not_found` 404 (also for trips you're not a member
  of), `conflict` 409, `too_large` 413, `invalid` 422, `rate_limited` 429, `server_error` 500.
- **Pagination**: list endpoints take `?limit=` (max 200) and `?cursor=`; responses are
  `{"items": [...], "next_cursor": "…" | null}`.
- **Sync**: list endpoints that support it take `?updated_since=<timestamp>` and include deleted
  objects as `{"id": 12, "deleted": true}`.
- **Idempotency**: creates accept a client-generated `client_id` (UUID). Repeating a request
  with the same `client_id` returns the object created the first time (200 instead of 201).
- **Versioning**: within v1 changes are additive only. Breaking changes go to `/api/v2/`, and v1
  stays until the app has moved.
