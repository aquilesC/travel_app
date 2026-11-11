# v3 #14: Authentication with django-allauth

**Status:** implemented 2026-11-11, tests in `accounts/tests_auth.py` and `trips/tests/test_membership.py`, verified on the live stack.

**Depends on:** —

## Scope

- `django-allauth` (account app only, no social providers yet) replaces `django.contrib.auth.urls`.
- Log in with **email + password** (`ACCOUNT_LOGIN_METHODS = {"email"}`); usernames remain for
  public profile URLs and are editable on `/account/`.
- Public signup is closed (adapter `is_open_for_signup → False`); accounts come from invites (#16)
  or the admin.
- Full password recovery: request → email with link → set new password → done
  (`/accounts/password/reset/…`). Password change at `/accounts/password/change/` (stays logged in).
- Email changes via allauth's email page; no verification step (`ACCOUNT_EMAIL_VERIFICATION="none"`).
- All allauth pages use the app layout (`templates/allauth/layouts/base.html`).
- Existing users get a primary, verified `EmailAddress` row (data migration).

## Acceptance Criteria

1. Logging in with email + password works; with the username it does not.
2. Password reset sends one email whose link sets a new password; the old one stops working.
3. `/accounts/signup/` shows "signup closed".
4. Anonymous `/account/` redirects to `/accounts/login/?next=/account/`.
