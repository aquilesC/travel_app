# v2 #10: Public profile

**Status:** implemented 2026-11-10, tests in `accounts/tests_profile.py` and `trips/tests/test_imports.py`, verified on the live stack.

**Depends on:** #9

## Scope

- `Trip.travellers` (M2M User): who went. New-trip form defaults to all users; data migration
  sets every existing trip to all users.
- `/u/<username>/` (anonymous): name, avatar, number of trips travelled, total km, and cards for
  the user's trips that have sharing on (linking to their share pages). 404 if the user doesn't
  exist or `Profile.is_public` is off. `noindex`.
- `/u/<username>/avatar/`: the avatar, served via X-Accel-Redirect; 404 when profile is private.
- Km per trip = sum of GPX track distances (cached summaries); for a trip without tracks, the
  straight-line (haversine) distance between consecutive check-ins (entry locations, photo GPS
  fallback) in time order. Private entries count toward the total but are never listed.
- Trips with sharing off count toward totals but are not listed.

## Acceptance Criteria

1. Profile shows trips count and km = GPX distance (trip with tracks) + check-in legs (trip
   without tracks), rounded to whole km.
2. A trip where the user is not a traveller is excluded from that user's numbers.
3. A non-shared trip counts but isn't listed; a shared one links to `/s/<token>/`.
4. Turning the profile private makes `/u/<username>/` and its avatar 404.
