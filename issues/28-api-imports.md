# v4 #28: Imports API (app photo picks → drafts)

**Status:** implemented 2026-11-11 on branch `worktree-bridge-cse_01M7JK1AVzjArdXY3fjss2Va` (not deployed), tests in `api/tests_imports.py`.

**Depends on:** #25, #26

The app uploads the photos you picked. The server groups them with the existing import pipeline
(`importing.py`) and you check the result on the existing review page.

## Scope

- `POST /api/v1/trips/{id}/imports` `{client_id}` → batch id. Uploads target it via #25.
- `GET /api/v1/imports/{id}`: items with status, proposed grouping (entries with time, place,
  photo ids) computed by `build_points` + `group_points`, using the uploader's positions (#26) and
  the trip's GPX tracks for photos without GPS. `review_url` = the web review page.
- `POST /api/v1/imports/{id}/commit` `{make_public}` → creates entries (`create_entries`), returns
  entry ids. `DELETE` discards (as `import_discard`).
- The web review page works for app-created batches unchanged (camera clock shift, etc.).
- Batches are per user; two travellers' imports don't merge (by design, cleanup later on the web).

## Acceptance Criteria

1. 40 photos picked across one day → batch → proposed entries match what the web import produces
   for the same files.
2. A photo without GPS is placed from the uploader's positions.
3. Committing twice doesn't duplicate entries.
4. Opening `review_url` in a logged-in browser shows the batch and can commit it.
