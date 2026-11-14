# EPIC v4: API-first website + TailwindCSS (companion to the iPhone app)

**Status:** planned 2026-11-11. Design: [`docs/designs/ios-trip-recorder.md`](../docs/designs/ios-trip-recorder.md).
App issues: [`issues/ios/`](ios/00-epic-ios-app.md).

## Deploy gate (Sri Lanka)

Code freeze for production is **2026-12-14 → return from Sri Lanka**. Work on these issues may happen
on branches during that window, but nothing deploys to `trips.aquiles.me` until the trip is over.
WhatsApp ingest (#7) keeps working throughout and is not removed by this epic.

## Goal

The website and the iPhone app evolve independently, with one versioned HTTP API between them.

- **Domain rules live in one place**: a service layer (`trips/services/`). Web views, the API and
  WhatsApp ingest all call it. No business logic in views.
- **`/api/v1/`** (django-ninja) exposes trips, entries, media, uploads, imports, positions and live
  location. Its OpenAPI schema is committed (`api/openapi.json`) and is the contract: the iOS app
  generates its client from it, and a test fails if the schema changes without updating the file.
- **The website stays server-rendered** Django templates (no SPA). Its JavaScript (map, reader,
  uploads) moves onto `/api/v1` with session auth, so the API is exercised by the web every day.
- **TailwindCSS** replaces `static/css/app.css`, built with the standalone CLI (no Node at runtime).

## Decisions

| Topic | Decision |
|---|---|
| API framework | django-ninja: typed schemas, OpenAPI generated from code, light. DRF rejected as heavier than needed |
| Auth | Web: Django session + CSRF. App: allauth headless "app" client with `X-Session-Token`. Invite-only stays; no API signup |
| Versioning | Path-versioned `/api/v1/`. Additive changes only within v1; breaking changes → `/api/v2/` with v1 kept until the app has moved |
| Contract | `api/openapi.json` committed; `manage.py export_openapi` regenerates; test compares |
| Idempotency | Every client-created object accepts a client UUID (`client_id`); repeated POSTs return the existing object |
| Live location | Members always see it. Share-link viewers only if enabled per trip, with delay (default 60 min) and rounding (default ~1 km). Positions inside a user's privacy zones never shown |
| Tailwind | v4 standalone CLI, pinned + checksummed in a Docker build stage; design tokens from today's `app.css` (incl. dark mode). Emails keep inline CSS |
| Repo | iOS app lives in `ios/` in this repo, so the contract file and both sides change in one PR when needed |

## Child issues

| # | Title | Priority | Depends on |
|---|---|---|---|
| [20](20-service-layer.md) | Service layer: move domain rules out of views and WhatsApp ingest | Critical | — |
| [21](21-api-foundation.md) | API foundation: django-ninja, `/api/v1`, errors, OpenAPI contract | Critical | 20 |
| [22](22-api-app-auth.md) | App authentication via allauth headless | Critical | 21 |
| [23](23-api-read.md) | Read API: me, trips, chapters, entries, media, map data; web JS moves over | High | 21 |
| [24](24-api-write.md) | Write API: entries (incl. app posts), chapters, tracks | High | 23 |
| [25](25-api-uploads.md) | Upload API: chunked uploads + hash pre-check; web uploader moves over | Critical | 21 |
| [26](26-positions.md) | Positions: model, batch ingest, map path, GPX export, used for photo placement | Critical | 21 |
| [27](27-live-location.md) | Live location on the trip and share pages, with privacy controls | High | 26 |
| [28](28-api-imports.md) | Imports API: photo batches from the app → drafts → web review | High | 25, 26 |
| [29](29-tailwind-foundation.md) | Tailwind foundation: build pipeline, tokens, base layout, components, forms | High | — |
| [30](30-tailwind-pages.md) | Tailwind: migrate every page, delete `app.css` | Medium | 29 |

### Dependency graph

```
#20 Services ─> #21 API foundation ─┬─> #22 App auth
                                    ├─> #23 Read ─> #24 Write
                                    ├─> #25 Uploads ──┐
                                    └─> #26 Positions ┴─> #28 Imports
                                              └─> #27 Live location
#29 Tailwind foundation ─> #30 Tailwind pages     (independent track, can run in parallel)
```

### Suggested order

#20 → #21 → #22 → #26 → #27 first: that's enough for app milestone "live location" (ios #1–#4).
Then #23/#24/#25 (app posting, ios #5–#6), then #28 (photo picker, ios #7). Tailwind runs alongside.

## Out of scope (later)

- Push notifications to family (APNs) for new public entries.
- Removing Twilio/WhatsApp ingest: decide after the app has carried one real trip.
- Public API for third parties, API keys, rate-limit tiers.
