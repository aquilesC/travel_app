# v2 #9: Account page (name, password, profile picture)

**Status:** implemented 2026-11-10, tests in `accounts/tests_profile.py` and `trips/tests/test_imports.py`, verified on the live stack.

**Depends on:** —

## Scope

- `/account/`: edit first name, last name, email, profile picture, "public profile" toggle,
  WhatsApp number (moved here from the admin).
- Profile picture: any photo (JPEG/PNG/HEIC/WebP ≤ 20 MB) → centre-cropped 512×512 WebP at
  `avatars/<user_id>/<uuid>.webp`; the previous file is deleted. "Remove picture" clears it.
- Password change via Django's `PasswordChangeView` at `/accounts/password_change/` with our own
  templates (not the admin look); the session stays logged in.
- `Profile` gains `avatar` (path), `is_public` (default True).
- Top bar shows the user's avatar/name linking to `/account/`.

## Acceptance Criteria

1. Saving the account form updates name/email; an invalid WhatsApp number shows a field error.
2. Uploading a 3000×2000 HEIC stores a 512×512 WebP and deletes the previous avatar file.
3. A non-image upload is rejected with a message; nothing is stored.
4. Changing the password with the wrong old password fails; with the right one succeeds and the
   user stays logged in.
