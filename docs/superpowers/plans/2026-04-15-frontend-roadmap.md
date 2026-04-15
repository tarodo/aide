# AIDE Frontend — 7-Phase Roadmap

**Date:** 2026-04-15
**Spec:** [docs/superpowers/specs/2026-04-15-frontend-mantine-spa-design.md](../specs/2026-04-15-frontend-mantine-spa-design.md)

## Purpose

The frontend MVP spans multiple vertical slices that each produce working software. Writing one monolithic plan would be unmanageable (200+ steps). This roadmap breaks the work into seven phases. Each phase ships a usable increment, has a dedicated detailed plan under `docs/superpowers/plans/`, and blocks only on its stated dependencies.

## Phase overview

| # | Phase | Goal | Entry | Exit |
|---|---|---|---|---|
| 1 | **Foundation** | Working login + empty app shell | None | User can log in, sees `AppShell` + empty `HomePage`, 401 triggers refresh, logout works |
| 2 | **Systems slice** | Full CRUD over `System` | Phase 1 | List/detail/create/edit/delete systems via UI; picker component usable by later phases |
| 3 | **Datasets** | Full CRUD over `Dataset` (polymorphic) | Phase 2 | List/detail/create/edit/delete datasets of all 5 kinds; sub-forms per kind with Zod discriminated union |
| 4 | **Schemas / Fields / Bindings** | Nested metadata authoring | Phase 3 | `FieldTree` renders + edits hierarchy; `DatasetSchema` versions listed/created; `FieldBinding` CRUD with pickers |
| 5 | **Crawl runs** | Read-only operational view | Phase 2 (systems picker), Phase 4 (optional deep links) | Global + per-system crawl lists; detail page with diff sections |
| 6 | **Admin hub** | Governance catalogs | Phase 1 | Read-only lists for kinds/flavors/data-types; CRUD for type-instances, cast-rules, credential-refs, users |
| 7 | **Hardening** | Production readiness | All prior phases | Empty states, loading skeletons, 404 polish, error-boundary UX, CI wiring, Dockerfile final, smoke E2E |

## Dependency graph

```
Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5
   │                                                  │
   └────────────────► Phase 6 ────────────────────────┘
                                                      │
                                                      ▼
                                                   Phase 7
```

Phase 6 only needs Phase 1 (auth + shell). It can be built in parallel with 2-5 if resources allow.

## Per-phase deliverables

### Phase 1 — Foundation

- `aide/frontend/` package scaffold (Vite + React + TS + Mantine)
- Theme (B/W palette, spacing, typography)
- Router (`/login`, `/`)
- OpenAPI type generation pipeline
- `ky` HTTP client with auth hooks (single-flight 401 refresh)
- `tokenStorage` (localStorage + in-memory split)
- `AuthContext`, `useAuth`, `RequireAuth`, `LoginPage`
- `AppShell` + `TopBar` + `SideNav` (stub nav links)
- `HomePage` stub
- Vitest + React Testing Library + MSW test harness
- ESLint + Prettier + `pnpm lint`/`typecheck`/`test` scripts

**Plan:** [2026-04-15-frontend-phase-1-foundation.md](2026-04-15-frontend-phase-1-foundation.md)

### Phase 2 — Systems slice

- `api/endpoints/systems.ts` hook set
- `SystemsListPage` with `DataTable`, pagination, search, filters (URL-synced)
- `SystemDetailPage` with metadata + action bar
- `SystemForm` (create / edit) with Zod + Mantine form
- `SystemPicker` component (reused across later phases)
- Delete confirmation flow
- Top-bar system selector wired to `SystemPicker`
- Endpoint module pattern codified as a template for phases 3-6
- Tests across the CRUD flow

**Plan:** (to be written after Phase 1 lands)

### Phase 3 — Datasets

- `api/endpoints/datasets.ts`
- `DatasetsPage` (per-system + all)
- `DatasetDetailPage` with tabs (Fields, Schemas, Meta — Fields/Schemas content stubbed)
- `DatasetForm` polymorphic dispatcher + five kind sub-forms under `features/datasets/kinds/`
- Zod discriminated union validator
- Kind-aware submission payload shaping
- Tests per kind (happy path + validation)

**Plan:** (to be written after Phase 2 lands)

### Phase 4 — Schemas / Fields / Bindings

- `api/endpoints/schemas.ts`, `fields.ts`, `bindings.ts`
- `FieldTree` component — hierarchical rendering, expand/collapse, search with ancestor auto-expand
- `FieldForm` with `PiiTagsInput`
- `DatasetSchemasPage` — versions list + create new (copies bindings from current)
- `SchemaDetailPage` — bindings table
- `Schema compare` diff view between two versions
- `BindingForm` with `FieldPicker`, `TypeInstancePicker`, position uniqueness handling
- Full tests including tree interactions and compare rendering

**Plan:** (to be written after Phase 3 lands)

### Phase 5 — Crawl runs

- `api/endpoints/crawls.ts`
- `/crawls` global list + `/systems/:id/crawls` per-system list
- `CrawlDetailPage` with KPI cards + collapsible `DiffSection` per table
- Diff payload parser (confirmed against crawler output during implementation)
- Read-only only in MVP (no apply/reject)
- Tests for diff rendering with fixture payloads

**Plan:** (to be written after Phase 4 lands)

### Phase 6 — Admin hub

- `/admin` landing hub page
- Read-only list pages: `SystemKinds`, `SystemFlavors`, `DataTypes` (filter by flavor)
- CRUD pages: `TypeInstance`, `CastRule`, `CredentialRef`, `User`
- Each entity reuses the pattern from Phase 2
- Uses the pickers built in earlier phases

**Plan:** (to be written in parallel with phases 2-5 if bandwidth allows)

### Phase 7 — Hardening

- Empty states and loading skeletons across all lists/details
- Global ErrorBoundary with recovery UX
- 404 route + missing-resource pages
- Notification styling polish (success/warn/error variants)
- Smoke E2E with Playwright covering the success-criteria flow from the spec
- CI workflow (`pnpm lint && typecheck && test`)
- Production `Dockerfile` + `docker-compose` integration finalised
- `make dev-frontend` / `make test-frontend` targets (optional, decided during implementation)

**Plan:** (to be written after Phase 6 lands)

## Review checkpoints

At the end of each phase, before moving to the next:
1. All phase-specific tests pass.
2. `pnpm lint && pnpm typecheck` clean.
3. Manual smoke check in the browser covering the phase's success criterion.
4. Commit messages follow `caveman:caveman-commit` style (no AI trailer).
5. Quick review of the next phase's plan to confirm dependencies still hold.

## Changing the roadmap

Phases are deliberately independent; if priorities shift, later plans can be reordered. If a phase grows beyond a reasonable plan size, split it into two and update this document.
