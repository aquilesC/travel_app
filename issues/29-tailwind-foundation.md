# v4 #29: Tailwind foundation

**Status:** implemented 2026-11-11 on branch `worktree-bridge-cse_01M7JK1AVzjArdXY3fjss2Va` (not deployed), tests in `trips/tests/test_forms_render.py`.

**Depends on:** —

## Scope

- **Build:** Tailwind v4 standalone CLI (no Node). Dockerfile gets a build stage that downloads a
  pinned `tailwindcss-linux-x64` release, verifies its SHA-256, and runs
  `tailwindcss -i static/src/app.css -o static/css/tailwind.css --minify`. The runtime image only gets the
  built CSS, and WhiteNoise serves it as today. The built file is gitignored.
- **Dev:** `compose.yaml` profile `dev` with a `tailwind` service running `--watch` on a bind mount.
  README documents it.
- **Sources:** `static/src/app.css` with `@import "tailwindcss";` and `@source` for `templates/`,
  `trips/templates/`, `accounts/templates/`, `static/js/` (classes set from JS).
- **Tokens** (`@theme`): colours from today's `app.css` (`bg`, `fg`, `muted`, `card`, `line`,
  `accent`, `danger`, `warn-bg`) with the dark-mode values via `prefers-color-scheme`; serif body
  (Georgia/Iowan) + system-ui headings, as now.
- **Components** as template partials in `templates/components/` (`button.html`, `card.html`,
  `messages.html`, `field.html`) plus `@layer components` for the few repeated patterns.
- **Forms:** a project form renderer (`FORM_RENDERER` + `templates/django/forms/`) so `{{ form }}`
  renders Tailwind-styled fields, help text and errors everywhere, allauth pages included.
- `base.html` (topbar, nav, messages) migrated. Pages that aren't migrated yet keep working because the
  old `app.css` rules are kept in a `legacy.css` loaded by `base.html` until #30 removes it.
  Tailwind's preflight reset is left out until then, so unmigrated pages keep their look.
- Optional before starting: run `/design-consultation` to decide whether the look changes or is
  only re-implemented.

## Acceptance Criteria

1. `docker compose build` produces an image whose `/static/css/app.css` contains used classes only.
2. No Node/npm in the runtime image.
3. Base layout matches today's light and dark appearance (screenshots before/after).
4. Every form on the site renders with the new field partial (tests render each form without errors).
