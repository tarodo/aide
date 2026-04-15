# AIDE Metastore Frontend — Design Spec

**Date:** 2026-04-15
**Status:** Draft for implementation planning
**Owner:** Data engineer / platform team

## 1. Overview & Scope

SPA frontend for AIDE Metastore. Single user persona — data engineer — performing three role-flavoured activities in one UI: platform administration, dataset/schema engineering, and governance review.

### Goals

- Provide a UI alternative to the SDK/CLI for daily metastore work.
- Cover full CRUD over the core domain entities needed by data engineers.
- Make crawl-run output inspectable visually (diff view).

### Non-goals (out of MVP)

- Multi-user RBAC / per-role permissions. All authenticated users share access.
- Full-text search across entities (filter-level search only).
- Lineage graph / ER-diagram visualization.
- Mobile / tablet layouts. Desktop-first, minimum viewport `1280px`.
- Crawl **apply / reject** from the UI. Crawl runs are view-only; applying happens via CLI/SDK.

### MVP entity coverage

| Entity | UI mode |
|---|---|
| User / Auth | login, refresh, logout |
| System | full CRUD |
| Dataset (5 polymorphic kinds) | full CRUD with per-kind form |
| Field | full CRUD + tree view + PII tags |
| DatasetSchema | full CRUD (versioned) |
| FieldBinding | full CRUD |
| CrawlRun | list + detail (read-only) |
| SystemKind / SystemFlavor / DataType / CastRule / TypeInstance / CredentialRef | read-only lists; used as pickers in forms above |

### Success criteria

A data engineer can, end-to-end through the UI:
1. Log in.
2. Register a new `System` linked to a `SystemFlavor` and optional `CredentialRef`.
3. Create a `Dataset` of any of the 5 kinds under that system.
4. Create a `DatasetSchema` v1 for the dataset.
5. Add `Field`s (including nested) and bind them via `FieldBinding` to a `TypeInstance`.
6. Open a `CrawlRun` detail for that system and read the diff.

## 2. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Bundler / dev server | Vite 5 | Fast HMR, de-facto standard. |
| UI framework | React 18 | Required by Mantine. |
| Component library | Mantine v7 | Explicit user preference. |
| Language | TypeScript (strict) | Catches drift with backend DTOs. |
| Routing | React Router v6 | Familiar, low-friction. |
| Server state | TanStack Query v5 | Cache, refetch, mutations. |
| Forms | `@mantine/form` + Zod via `zodResolver` | Good integration with Mantine; Zod gives typed schemas. |
| API types | `openapi-typescript` codegen from FastAPI `/openapi.json` | Zero drift with backend. |
| HTTP client | `ky` (thin fetch wrapper) | Retries, JSON, hooks for auth header. |
| Icons | `@tabler/icons-react` (stroke 1.5) | Native fit with Mantine. |
| Testing | Vitest + React Testing Library + MSW | Unit, component, integration. |
| E2E | Playwright (deferred to post-MVP) | Golden-path regression. |
| Lint/format | ESLint + Prettier | Standard. |
| Package manager | pnpm | Speed, disk dedup. |

Out-of-scope for MVP: Redux / Zustand (TanStack Query covers server state; `useState`/`useReducer` for local UI), Storybook, visual regression tools, automated accessibility testing, dark mode (Mantine supports it, but add later).

## 3. Project Structure

New package `aide/frontend/` alongside `backend/`, `sdk/`, `crawler/`. Feature-based folder layout.

```
frontend/
├── package.json                     # name: "@aide/frontend"
├── tsconfig.json
├── vite.config.ts
├── index.html
├── .eslintrc.cjs
├── Dockerfile                       # nginx-based for prod
├── scripts/
│   └── generate-types.sh            # curl openapi.json → openapi-typescript
├── public/
└── src/
    ├── main.tsx                     # root, MantineProvider, QueryClientProvider, Router
    ├── app/
    │   ├── router.tsx               # route tree
    │   ├── theme.ts                 # Mantine theme (B/W palette)
    │   └── layout/
    │       ├── AppShell.tsx         # topbar + sidebar
    │       ├── TopBar.tsx           # logo, system selector, user menu
    │       └── SideNav.tsx          # context-aware nav
    ├── api/
    │   ├── client.ts                # ky instance + auth/refresh hooks
    │   ├── types.gen.ts             # GENERATED — do not edit
    │   └── endpoints/
    │       ├── systems.ts           # typed fetchers + TanStack Query hooks
    │       ├── datasets.ts
    │       ├── fields.ts
    │       ├── schemas.ts
    │       ├── bindings.ts
    │       ├── crawls.ts
    │       ├── types.ts             # data-types, type-instances, cast-rules
    │       ├── flavors.ts           # system-kinds, system-flavors
    │       └── credentials.ts
    ├── features/
    │   ├── auth/
    │   │   ├── AuthContext.tsx
    │   │   ├── LoginPage.tsx
    │   │   ├── useAuth.ts
    │   │   ├── RequireAuth.tsx
    │   │   └── tokenStorage.ts
    │   ├── home/
    │   │   └── HomePage.tsx         # global dashboard
    │   ├── systems/
    │   │   ├── SystemsListPage.tsx
    │   │   ├── SystemDetailPage.tsx
    │   │   ├── SystemForm.tsx
    │   │   └── SystemPicker.tsx
    │   ├── datasets/
    │   │   ├── DatasetsPage.tsx
    │   │   ├── DatasetDetailPage.tsx
    │   │   ├── DatasetForm.tsx      # polymorphic dispatcher
    │   │   └── kinds/
    │   │       ├── RdbmsFields.tsx
    │   │       ├── KafkaFields.tsx
    │   │       ├── StorageFields.tsx
    │   │       ├── SftpFields.tsx
    │   │       └── HiveFields.tsx
    │   ├── fields/
    │   │   ├── FieldTree.tsx
    │   │   ├── FieldForm.tsx
    │   │   └── PiiTagsInput.tsx
    │   ├── schemas/
    │   │   ├── DatasetSchemasPage.tsx
    │   │   ├── SchemaDetailPage.tsx
    │   │   └── VersionPicker.tsx
    │   ├── bindings/
    │   │   └── BindingForm.tsx
    │   ├── crawls/
    │   │   ├── CrawlsPage.tsx
    │   │   ├── CrawlDetailPage.tsx
    │   │   └── DiffSection.tsx
    │   └── admin/                   # users/types/rules/flavors/credentials
    ├── shared/
    │   ├── components/              # DataTable, ConfirmModal, PageHeader, JsonField
    │   ├── hooks/                   # usePagination, useDebounce, useUrlState
    │   ├── utils/                   # errorMapper, formatters
    │   └── types/                   # domain helper types
    └── tests/
        ├── setup.ts
        ├── msw/handlers.ts
        ├── fixtures/
        └── test-utils.tsx
```

### Key conventions

- One module per entity under `api/endpoints/`. Module exports typed fetchers plus `use*` TanStack Query hooks. Single source of endpoint truth.
- `features/*` hold domain screens, forms, feature-local hooks. No cross-feature imports except through `shared/`.
- `shared/*` reserved for truly generic building blocks. Resist promoting feature-specific helpers here.

## 4. Routes & Information Architecture

```
/login                                                     public

── app shell (RequireAuth) ──
/                                                          Home (global dashboard)
/systems                                                   all systems, list
/systems/new                                               create
/systems/:systemId                                         system overview
/systems/:systemId/edit
/systems/:systemId/datasets                                datasets of system
/systems/:systemId/datasets/new
/systems/:systemId/datasets/:datasetId                     dataset detail (tabs: Fields, Schemas, Meta)
/systems/:systemId/datasets/:datasetId/edit
/systems/:systemId/datasets/:datasetId/fields/:fieldId     field detail/edit
/systems/:systemId/datasets/:datasetId/schemas/:schemaId   schema version + bindings
/systems/:systemId/crawls                                  crawls of system
/systems/:systemId/crawls/:crawlId                         crawl detail (diff)

/crawls                                                    all crawls (cross-system)
/crawls/:crawlId                                           redirects to /systems/.../crawls/:id

/admin                                                     flat hub page
/admin/users
/admin/system-kinds                                        read-only
/admin/system-flavors                                      read-only
/admin/data-types                                          read-only, filter by flavor
/admin/type-instances
/admin/cast-rules
/admin/credential-refs

/404
```

### TopBar system selector

`Select` in the header. Switching to a different system:
- If URL matches `/systems/:systemId/<rest>`, replace `:systemId` and keep `<rest>`.
- Otherwise navigate to `/systems/:systemId`.

### Breadcrumbs

Rendered on all in-system routes. Example: `pg-prod › Datasets › orders › Schema v2`.

### Deep-linking

Tables encode page/size/search/filters in URL query params. Reloading the page must preserve state.

## 5. API Layer

### Type generation

```bash
# scripts/generate-types.sh
npx openapi-typescript http://localhost:8001/openapi.json -o src/api/types.gen.ts
```

Exposed as `pnpm gen:types`. Requires the backend to be running. `types.gen.ts` is committed and never hand-edited.

### HTTP client

`src/api/client.ts` wraps `ky` with:
- `prefixUrl` from `VITE_API_URL` env (defaults to `/api/v1`).
- `beforeRequest` hook injecting `Authorization: Bearer <access>`.
- `afterResponse` hook handling 401: single-flight refresh, retry once on success, redirect to `/login` on failure.

Single-flight refresh: a module-level `refreshPromise: Promise<string> | null` ensures concurrent 401s share one refresh attempt.

### Endpoint module pattern

Each entity gets a file under `api/endpoints/` that exports:
- A `queryKeys` object (`all`, `list(params)`, `detail(id)`) for cache invalidation.
- Query hooks (`useSystemsList`, `useSystem`) wrapping `useQuery`.
- Mutation hooks (`useCreateSystem`, `useUpdateSystem`, `useDeleteSystem`) wrapping `useMutation` with `onSuccess: qc.invalidateQueries(...)`.

Example:

```ts
import { api } from '../client';
import type { components } from '../types.gen';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

type SystemRead = components['schemas']['SystemRead'];
type SystemCreate = components['schemas']['SystemCreate'];

export const systemsKeys = {
  all: ['systems'] as const,
  list: (params: ListParams) => ['systems', 'list', params] as const,
  detail: (id: string) => ['systems', 'detail', id] as const,
};

export const useSystemsList = (params: ListParams) =>
  useQuery({
    queryKey: systemsKeys.list(params),
    queryFn: () => api.get('systems', { searchParams: params }).json(),
  });
```

### Error handling

- Backend returns machine-readable error codes (see `backend/core/errors.py`). A `shared/utils/errorMapper.ts` turns codes into human messages.
- 4xx validation (422) maps `detail[].loc` to `form.setFieldError(...)`.
- Business errors (409 duplicate, etc.) surface as Mantine `notifications`.
- 404 in a detail query renders an empty/not-found state, not a toast.
- 5xx triggers a toast and is logged; Sentry wiring deferred.

### Pagination

Backend uses `PaginatedResponse_<T>_` with `page`, `size`, `total`. `DataTable` reads those fields and syncs page/size into URL via `useUrlState`.

## 6. Auth Flow

### Backend contract (assumed; verified during implementation)

- `POST /api/v1/login/` — OAuth2 password flow → `{access_token, refresh_token}`.
- `POST /api/v1/login/refresh` — new access from refresh token.
- JWT HS256, access short-lived, refresh long-lived.

**Gap flag:** if `/login/refresh` is not implemented, implementation plan must call this out and propose either adding it or falling back to re-login on expiry.

### Token storage

- `accessToken` — in-memory (React context + ref). Not stored in `localStorage` to limit XSS blast radius.
- `refreshToken` — `localStorage`. Acceptable for a prototype; migrate to HttpOnly cookie post-MVP if backend supports it.
- App boot: if `localStorage` contains a refresh token, attempt refresh. Success → populate in-memory access → hydrate app. Failure → clear tokens, redirect to `/login`.

### Components

```
features/auth/
├── AuthContext.tsx       # { user, accessToken, login(), logout(), isLoading }
├── useAuth.ts
├── LoginPage.tsx         # Mantine form, POST /login/, on success navigate('/')
├── RequireAuth.tsx       # gate — redirects to /login if unauthenticated
└── tokenStorage.ts       # localStorage wrapper
```

### Protected routes

```tsx
<Route path="/login" element={<LoginPage />} />
<Route element={<RequireAuth><AppShell /></RequireAuth>}>
  <Route path="/" element={<HomePage />} />
  <Route path="/systems" element={<SystemsListPage />} />
  {/* ... */}
</Route>
```

### Logout

Clear tokens from memory and storage, reset `QueryClient`, navigate to `/login`.

## 7. Forms

### Base pattern

`@mantine/form` + Zod via `zodResolver`. Schemas live next to the form. We do **not** generate Zod from OpenAPI (lossy); TypeScript types come from the OpenAPI codegen, Zod schemas are hand-written for UI validation only. The server remains the source of truth.

```tsx
const schema = z.object({
  code: z.string().min(1).max(255),
  name: z.string().min(1),
  flavor_id: z.string().uuid(),
  is_active: z.boolean(),
});

type Values = z.infer<typeof schema>;

const form = useForm<Values>({
  initialValues: { code: '', name: '', flavor_id: '', is_active: true },
  validate: zodResolver(schema),
});
```

### Polymorphic Dataset form

`DatasetForm` handles 5 kinds (`rdbms`, `kafka`, `storage`, `sftp`, `hive`). Architecture:
- Top of the form: common fields (`system_id` picker — fixed when coming from a system context, `object_name`, `layer`, `is_active`, `extra`).
- `kind` selector as Mantine `SegmentedControl` (only on create — immutable after).
- Kind-specific sub-form under `features/datasets/kinds/*Fields.tsx`.
- Zod schema is a `z.discriminatedUnion('kind', [...])`.

### Complex input types

| Type | Widget |
|---|---|
| `JSONB` (`extra`, `uq_constraints`, `tblproperties`, `schema`) | Mantine `JsonInput`. Monaco deferred — bundle cost (~3MB) without JSON-Schema autocomplete is not worth it for MVP. |
| `ARRAY(String)` (`tags`, `pk_columns`, `partition_by`, `key_columns`, ...) | Mantine `TagsInput`. |
| PII tags on Field | `PiiTagsInput` — wraps `TagsInput` with common suggestions (`email`, `phone`, `name`, `id`, `address`). |

### FieldBinding

- `field_id` — `FieldPicker` scoped to the dataset.
- `type_instance_id` — `TypeInstancePicker` of existing `TypeInstance`s. **No inline creation** in MVP — inline creation promotes duplicate `varchar(255)` rows. `TypeInstance` is a shared, reusable catalog; creation lives on `/admin/type-instances`.
- `position` — `NumberInput`. Unique per schema version; surface 409 conflicts as toasts.
- `is_nullable` — `Switch`.

### DatasetSchema

- `version_num` — `NumberInput`, initial value = `maxExistingVersion + 1`. 409 on conflict → toast.
- `schema` (JSONB) — `JsonInput`.

### Pickers (reusable)

`SystemPicker`, `FlavorPicker`, `DataTypePicker`, `FieldPicker`, `TypeInstancePicker`, `CredentialRefPicker`. All built on `Select` with async search via the corresponding `use*List` hook.

### Submission

- `onSubmit` → `mutation.mutate()`.
- On success: invalidate list queries, show `notifications.show({ color: 'green', ... })`, navigate to detail page.
- On 422: map `detail[].loc` to field errors via `form.setFieldError`.
- On business error (409, etc.): translate via `errorMapper`, show toast, keep form values intact.

## 8. Key UX Patterns

### 8.1 Field tree

`Field.parent_id` yields a hierarchy (struct-in-struct for nested RDBMS rows, JSON payloads, Kafka schemas). Flat lists lose that structure.

- Tree rendered with `▸`/`▾` toggle per parent. Indent 24px per level.
- PII badge pinned inline next to name. Badge text-only (`PII`) to stay accessible.
- Meta on the right (type, position, nullable).
- Search filters in real time and auto-expands ancestors of matches.
- Row click opens an edit drawer (Mantine `Drawer`) on the right with the field form.
- `+ Add field` button — parent-aware (adds under current selection if any, else root).

### 8.2 Schema versions

- Left: vertical list of versions (`v3`, `v2`, `v1`) with field count and `updated_at`.
- Right: binding table of selected version.
- `+ New version` button copies bindings from `current` to create `max + 1`.
- `Compare → vN` view: shows diff — rows gain a right-column annotation (`+ added in v3`, `~ type changed`, `- removed`). Row backgrounds tinted subtly (green/red wash) plus an icon, never color alone.

### 8.3 CrawlRun detail (read-only in MVP)

- Header strip: four KPI cards — `Added`, `Removed`, `Changed`, `Duration`.
- Body: collapsible sections per table. Each section lists column-level diffs in a monospace row format (`+ column: tracking_number · varchar(64) · NULL`, `~ column: total · int → numeric(10,2)`).
- Colour accents are the only deviation from pure B/W — subtle tinted backgrounds (`#f5fbf5` green wash for add, `#fdf5f5` red wash for remove/change) combined with an icon and textual marker (`+`/`-`/`~`). Must remain legible with colour disabled.
- No apply/reject action in MVP.

## 9. Styling & Mantine Theme

### Palette

```ts
// src/app/theme.ts (sketch — not final)
export const theme = createTheme({
  primaryColor: 'black',
  primaryShade: 9,
  colors: {
    black: [
      '#f7f7f7', // 0 — bg hover
      '#ececec', // 1 — light borders
      '#d9d9d9', // 2 — borders
      '#b8b8b8', // 3 — muted text
      '#8a8a8a', // 4 — secondary text
      '#666666', // 5 — icons
      '#444444', // 6
      '#2a2a2a', // 7
      '#141414', // 8 — primary hover
      '#000000', // 9 — primary button, headings
    ],
    // Subtle accent ramps, only used to tint diff rows / badges.
    // Low-saturation: diff signal must remain readable without colour (icon + text).
    diffAdded:   ['#f5fbf5', '#e8f3e8', '#c9e4c9', '#a6d3a6', '#83c283', '#5cb05c', '#3a9e3a', '#2d842d', '#226a22', '#0a6b3a'],
    diffRemoved: ['#fdf5f5', '#fae7e7', '#f2caca', '#e9a6a6', '#e08383', '#d85c5c', '#d03a3a', '#b92d2d', '#9d2222', '#cc3333'],
  },
  fontFamily: '-apple-system, "Inter", "Segoe UI", sans-serif',
  fontFamilyMonospace: '"JetBrains Mono", "SF Mono", monospace',
  headings: { fontFamily: 'inherit', fontWeight: '600' },
  radius: { xs: '4px', sm: '6px', md: '8px', lg: '12px', xl: '16px' },
  defaultRadius: 'sm',
  spacing: { xs: '6px', sm: '10px', md: '14px', lg: '20px', xl: '28px' },
});
```

### Component conventions

- Primary button: `bg black[9]`, `color white`, `radius sm`.
- Table rows: `border-bottom 1px black[1]`, hover `bg black[0]`.
- Cards: `border 1px black[1]`, `radius sm`, shadow reserved for modals/menus.
- Inputs: Mantine default; focus ring `black[9]`.
- Badges (PII, status): `bg black[9]`, `color white`.

### Typography scale

- h1 / page title — 24 / 600
- h2 / section — 18 / 600
- body — 14 / 400
- caption — 12 / 400, `color black[4]`
- uppercase label — 10 / 500, `letter-spacing 0.5px`, `color black[4]`

### Density

Comfortable (table rows 32-36px tall, 8px vertical padding). A compact `size="xs"` mode is provided for dense tables (Fields, Bindings).

### Spacing

Always via theme tokens — no magic numbers inside components.

### Icons

`@tabler/icons-react` with `stroke={1.5}`.

### Dark mode

Deferred. Locked to light (`colorScheme: 'light'`). Theme is already structured so a dark ramp can be swapped in later.

## 10. Testing Strategy

MVP emphasises critical paths over coverage targets. Expand when regressions bite.

| Layer | Tooling | Scope |
|---|---|---|
| Unit | Vitest | utils, Zod schemas, `tokenStorage`, `useUrlState` |
| Component | Vitest + React Testing Library | forms (success + validation), tables, pickers, `FieldTree` expand/collapse |
| Integration | Vitest + MSW | endpoint hooks, TanStack Query cache behaviour, auth refresh flow |
| E2E | Playwright (post-MVP) | login → create system → dataset → schema → field golden path |

### MSW setup

`src/tests/msw/handlers.ts` mocks `/api/v1/*`. Fixtures reuse `types.gen.ts` so they stay type-safe. Component and integration tests run without a live backend.

### Required MVP tests

1. Login: valid credentials redirect; invalid show error.
2. 401 → refresh: expired access triggers one refresh and a retry; two concurrent 401s share one refresh.
3. `SystemForm`: Zod blocks empty `code`; successful submit invalidates the list query.
4. `DatasetForm` polymorphism: switching `kind` swaps sub-fields; submit payload matches the selected kind.
5. `FieldTree`: expand/collapse, search filters and auto-expands ancestors.
6. Schema compare: diff renders added/removed/changed annotations.
7. `CrawlRunDetail`: renders KPI cards and table/column sections from a fixture payload.

### Out of MVP

Visual regression, automated a11y, performance tests, Storybook.

### CI

Add a frontend job running `pnpm lint && pnpm typecheck && pnpm test`. A `make test-frontend` target is optional and can be decided during implementation.

## 11. Deployment

- `frontend/Dockerfile` — multi-stage (`node:lts` build → `nginx:alpine` serve).
- `docker-compose.yml` gains a `frontend` service behind nginx that reverse-proxies `/api/v1` to the `app` service. Compose will be the integration point for local dev; exact networking finalised during implementation.
- `VITE_API_URL` consumed at build time for non-compose deploys.

## 12. Open Questions / Follow-ups

These do not block the spec but should be resolved during planning:

1. Does `POST /api/v1/login/refresh` exist? If not, plan must add it or fall back to re-login on expiry.
2. Does the backend return a standard `PaginatedResponse_<T>_` shape for every list endpoint? Confirm at implementation time; `DataTable` depends on it.
3. `CrawlRun` diff payload shape — verify against `crawler` output to finalise `DiffSection` rendering.
4. Whether to add a frontend-specific Makefile target (`make test-frontend`, `make dev-frontend`) or keep commands inside `frontend/` only.
5. CORS vs reverse-proxy: compose-level nginx proxy means no CORS headers needed. If the frontend ever runs standalone against a remote backend, the backend must enable CORS for that origin. Plan should confirm current `CORS_ORIGINS` config covers the dev flow.

## 13. Implementation Phasing (indicative)

This spec deliberately avoids a detailed plan (that belongs in the implementation plan), but the natural phasing is:

1. **Foundation** — `aide/frontend/` skeleton, Vite + TS + Mantine + theme, `types.gen.ts` pipeline, `ky` client with auth hooks, `AuthContext` + `LoginPage` + `RequireAuth`, `AppShell` layout, global `HomePage` stub.
2. **Vertical slice: Systems** — list / detail / form / delete, invalidation, URL state, error mapping. Validates the pattern.
3. **Datasets (polymorphic)** — list / detail / form with 5 kind variants, schemas tab stub.
4. **Fields + Schemas + Bindings** — `FieldTree`, schema versions, binding table, compare view.
5. **Crawl runs** — global list, per-system list, detail diff view.
6. **Admin hub** — read-only lists for kinds/flavors/data-types; CRUD for `TypeInstance`, `CastRule`, `CredentialRef`, `User`.
7. **Hardening** — remaining tests, error polish, empty states, 404 routing, loading states.
