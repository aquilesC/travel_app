# v4 #22: App authentication (allauth headless)

**Status:** implemented 2026-11-11 on branch `worktree-bridge-cse_01M7JK1AVzjArdXY3fjss2Va` (not deployed), tests in `api/tests.py`.

**Depends on:** #21

## Scope

- Enable `allauth.headless` with clients `["app"]` only (the browser keeps normal allauth pages),
  mounted at `/_allauth/`. `HEADLESS_ONLY = False`.
- App flow: `POST /_allauth/app/v1/auth/login` (email + password) → session token; the app sends it as
  `X-Session-Token`. `DELETE /_allauth/app/v1/auth/session` logs out.
- Signup stays closed for the app client too (same invite-only adapter as the web).
- API auth: accept either the Django session (web) or `X-Session-Token` (app), using allauth's ninja
  integration (`allauth.headless.contrib.ninja`; verify it exists in the pinned 65.21, otherwise a
  small custom `APIKeyHeader` auth that resolves the token through allauth's token strategy).
  Token-authenticated requests skip CSRF.
- `GET /api/v1/me`: id, name, username, avatar URL, privacy zones (from #27, empty until then).
- Account page lists active app sessions (device name sent by the app, last seen) with "Sign out".
- Password reset stays web-only; the app links to it.

## Acceptance Criteria

1. Login with valid credentials returns a token; `GET /api/v1/me` with it → 200.
2. Wrong password → 401; 10 failed logins in 5 min from one IP → 429 (allauth rate limits).
3. Signup via the headless app client is refused.
4. Revoking a session on the account page makes that token return 401 immediately.
5. A token-authenticated POST without CSRF succeeds; a cookie-authenticated POST without CSRF fails.
