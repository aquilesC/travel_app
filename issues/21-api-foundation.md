# v4 #21: API foundation

**Status:** implemented 2026-11-11 on branch `worktree-bridge-cse_01M7JK1AVzjArdXY3fjss2Va` (not deployed), tests in `api/tests.py`.

**Depends on:** #20

## Scope

- Add `django-ninja` (check Django 6.1 support for the pinned version). New app `api/` with
  `NinjaAPI(version="1", urls_namespace="api-v1")` mounted at `/api/v1/`.
- **Login middleware:** `LoginRequiredMiddleware` would redirect API calls to the login page. Mark the
  API's views `login_not_required` and do auth in ninja instead. Unauthenticated → `401` JSON, never a redirect.
- **Web auth:** ninja `django_auth` (session) with CSRF enforced on unsafe methods. Token auth is #22.
- **Errors:** one JSON shape `{"error": {"code": "not_found", "message": "…", "fields": {…}}}`;
  service errors from #20 map to 404/403/422; unhandled → 500 with the same shape.
- **Conventions:** ISO 8601 UTC timestamps, IDs as integers (UUIDs for uploads/batches), cursor
  pagination (`?cursor=&limit=`), `?updated_since=` for incremental sync, `client_id` (UUID) for
  idempotent creates. Document these in `api/README.md`.
- **Contract:** `manage.py export_openapi > api/openapi.json`; a test fails if the generated schema
  differs from the committed file. `/api/v1/docs` (Swagger UI) only for staff.
- `GET /api/v1/health` (no auth) returns API version and server time (used by the app to detect clock skew).
- nginx: `/api/` proxied like everything else; `client_max_body_size` unchanged (uploads are chunked).

## Acceptance Criteria

1. `GET /api/v1/health` → 200 JSON without login; any other endpoint without auth → 401 JSON.
2. A POST with session but without CSRF token → 403 JSON.
3. Schema-drift test fails when an endpoint changes and `api/openapi.json` isn't regenerated.
4. Error responses for 401/403/404/422/500 all match the documented shape (tests).
