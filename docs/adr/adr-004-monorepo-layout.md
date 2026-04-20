# ADR-004: Monorepo Layout and Schema Re-export Pattern

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

AIDE ships four Python deliverables out of a single repository:

| Package | Role |
|---------|------|
| `aide` (root) | FastAPI metastore — the server |
| `aide-schemas` | Pydantic DTOs shared between server, SDK, and clients |
| `aide-sdk` | Async HTTP client that talks to the server |
| `aide-crawler` | RDBMS metadata crawler CLI that uses the SDK |

These deliverables are linked in a dependency chain:

```
aide-schemas  ─┬─► backend (server)
               ├─► aide-sdk ─► aide-crawler
               └─► aide-crawler
```

If the three non-server packages lived in separate repositories we would
pay the usual cost: version skew between server and clients, release-
coordination overhead, and a split code-review surface. On the other
hand, if everything lived in a single flat package we would lose the
ability to publish the SDK or the schemas independently, and we would
force SDK/crawler consumers to pull the server's dependency tree
(SQLAlchemy, asyncpg, alembic, …) for no reason.

The second pressure is the **DTO boundary**: the server needs to both
*consume* shared DTOs and add server-only helpers (filter schemas,
pagination, auth tokens, batch envelopes). We need a consistent story
for "where do request/response schemas live, and where do I import them
from inside the backend?"

## 2. Options Considered

### Option A: Four packages in one monorepo, wired via `[tool.uv.sources]`; backend re-exports from `aide_schemas` — **chosen**

- One root `pyproject.toml` per deliverable (root, `schemas/`, `sdk/`,
  `crawler/`).
- Root `pyproject.toml` lists `aide-schemas` as a dependency and points
  `[tool.uv.sources]` at the local `schemas/` path for editable install.
- `sdk/` and `crawler/` do the same for their parents.
- `backend/schemas/<entity>.py` re-exports from `aide_schemas.<entity>`
  so backend code can keep its historical `from backend.schemas.<entity>
  import …` imports while the real definitions live once in
  `aide-schemas`.

**Pros:**

- Each package is independently installable (and publishable) via
  `uv pip install -e <path>` or a wheel.
- SDK / crawler consumers pull only pydantic — none of the server's
  dependency tree.
- Schemas change in one place; server and SDK see the same type on the
  same commit, so request/response contracts cannot drift within a
  release.
- The re-export shim gives the backend a stable import path
  (`backend.schemas.system`) without carrying the canonical definitions.
- `uv sync` resolves all four packages in one step; developers get the
  full workspace with no extra bootstrap.

**Cons:**

- Two files per shared entity (one in `schemas/aide_schemas/` and one
  in `backend/schemas/`). Keeping `backend/schemas/__init__.py` exports
  in sync with the canonical package is manual.
- Hatchling + editable sources are unfamiliar to contributors who expect
  a standard single-package layout.
- Adding a new schema requires touching both locations.

### Option B: Single flat package, no re-export

All DTOs live in `backend/schemas/` directly. SDK and crawler live
outside the repo (or inline as submodules) and copy DTOs.

**Pros:** minimal file count.
**Cons:** SDK consumers pull the server's dependency tree; schemas drift
between server and clients; cross-repo releases become a coordination
task instead of a commit.

### Option C: Separate repositories per deliverable

`aide`, `aide-schemas`, `aide-sdk`, `aide-crawler` as independent
repositories, published to a package index.

**Pros:** hard package boundary; cannot accidentally import server code
from SDK.
**Cons:** every schema change requires a release and a version bump in
the server and SDK simultaneously; contributors must clone and wire
four repos for local development; cross-package refactors become
multi-PR coordination.

### Option D: Monorepo without the re-export shim

Schemas live only in `aide-schemas`; backend code imports directly from
`aide_schemas.system import SystemCreate`.

**Pros:** one source of truth; no sync burden on `backend/schemas/`.
**Cons:** backwards-incompatible for existing imports; mixes "shared"
and "backend-only" schemas under one namespace (the shim is the line
between them — see §5 on the boundary); harder to add a backend-only
subclass of a shared DTO under a single import path.

## 3. Trade-off Analysis

Option C buys isolation at the cost of development friction; with one
team and one deployment cadence it is the wrong trade. Option B collapses
the dependency tree that keeps SDK consumers lightweight. Option D is
appealing but loses the "one import path for everything a backend file
needs" ergonomic — in practice the backend also has filter schemas,
pagination aliases, and error envelopes that do not belong in the shared
package, and the shim lets both kinds co-exist under `backend.schemas`.

Option A matches the growth pattern we already have: one team, one
release cadence, multiple deliverables from one codebase.

## 4. Recommendation

Adopt Option A. Treat `aide-schemas` as the canonical DTO contract and
use `backend/schemas/` as the single namespace from which backend code
imports both shared and backend-only schemas.

## 5. Implementation Notes

### Package boundaries

```
repo root/
├── pyproject.toml           # "aide" (the server)     depends on: aide-schemas
├── backend/                 # server source
├── schemas/                 # "aide-schemas"          depends on: pydantic[email] only
│   └── aide_schemas/
├── sdk/                     # "aide-sdk"              depends on: aide-schemas, httpx
│   └── aide_sdk/
└── crawler/                 # "aide-crawler"          depends on: aide-sdk, aide-schemas
    └── aide_crawler/
```

Dependency rule: **lower packages never import from higher ones.**

- `aide-schemas` has zero project-internal dependencies. It must never
  import from `backend`, `aide_sdk`, or `aide_crawler`.
- `aide-sdk` depends only on `aide-schemas`. No backend imports.
- `aide-crawler` depends on `aide-sdk` and `aide-schemas`.
- The backend (root package) depends on `aide-schemas`, never on
  `aide-sdk` or `aide-crawler`.

Workspace wiring lives in each package's `[tool.uv.sources]`:

```toml
# root pyproject.toml
[tool.uv.sources]
aide-schemas = { path = "schemas", editable = true }
aide-sdk     = { path = "sdk",     editable = true }
aide-crawler = { path = "crawler", editable = true }
```

Sibling packages point back up with `../schemas` / `../sdk`. `uv sync`
from the root installs all four in editable mode.

### What goes in `aide-schemas` vs `backend/schemas/`

| Schema kind | Lives in | Rationale |
|-------------|----------|-----------|
| Entity `Create` / `Update` / `Read` | `aide-schemas` | SDK clients deserialize these |
| Shared mixins (`MetaDataMixin`, `NoteMixin`, `VersionedUpdateMixin`) | `aide-schemas` | Referenced by entity DTOs |
| Pagination envelope (`Page[T]`) | `aide-schemas` | SDK returns paginated reads |
| Batch request/response envelopes | `aide-schemas` | SDK uses batch endpoints |
| Per-entity filter models (`SystemFilter`, …) | `backend/schemas/` only | Filtering is a server-side concern |
| Sort allow-lists (`SYSTEM_SORTABLE`) | `backend/schemas/` only | Server-only |
| `ErrorResponse` envelope | `backend/schemas/` only | Server-produced, not consumed by SDK types |
| JWT `Token` / `TokenData` | `backend/schemas/` only | Auth is server-internal |

Shared DTOs must remain importable by anyone who only has pydantic
installed — keep `aide-schemas` free of SQLAlchemy, FastAPI, httpx,
structlog, and any other server dependency.

### The re-export shim

`backend/schemas/<entity>.py` must be a thin pass-through. The
convention uses `as` aliasing to mark imports as intentional re-exports
(so mypy treats them as public and does not flag them as unused):

```python
# backend/schemas/system.py
from aide_schemas.system import (
    SystemCreate as SystemCreate,
    SystemRead as SystemRead,
    SystemUpdate as SystemUpdate,
)
```

`backend/schemas/__init__.py` re-exports the entity names so
`from backend.schemas import SystemRead` keeps working.

Do not add new fields or validators inside the shim — they belong in
`aide_schemas`. If a backend-only variant is genuinely needed (e.g. an
internal admin payload that the SDK should never see), put it in a
separately-named module under `backend/schemas/` — not in the shim file
for the shared DTO.

### Imports inside the backend

Backend code imports through the shim:

```python
from backend.schemas.system import SystemCreate, SystemRead, SystemUpdate
from backend.schemas.filters import SystemFilter, SYSTEM_SORTABLE
from backend.schemas.pagination import Page
```

Importing `aide_schemas.*` directly from backend files works but bypasses
the convention — prefer `backend.schemas.*` for consistency and to keep
future shim-level changes (e.g. versioned schemas) at one seam.

### Adding a new shared DTO

1. Create `schemas/aide_schemas/<entity>.py` with the Pydantic classes.
2. Export them from `schemas/aide_schemas/__init__.py` (if the package
   exposes a flat `__all__`).
3. Create `backend/schemas/<entity>.py` with `from aide_schemas.<entity>
   import X as X, Y as Y, Z as Z`.
4. Add the names to `backend/schemas/__init__.py`'s imports and
   `__all__`.
5. Run `make format` — the import order is checked.

### Testing

- SDK and crawler tests run standalone: `cd sdk && uv run pytest tests/`
  and `cd crawler && uv run pytest tests/`. They need no database.
- Backend tests run in Docker via `make test-docker` (ADR-007).
- When adding a new package to the workspace or changing dependencies
  with `uv sync`, rebuild the test image:
  `docker compose build test`. Otherwise the test container will miss
  the new module — the failure mode is a `ModuleNotFoundError` at
  collection time (noted in CLAUDE.md).

## 6. Consequences

- **Easier:** shipping the SDK or crawler independently; keeping SDK
  consumers on a minimal dependency tree; preventing DTO drift within a
  release.
- **Harder:** adding a new entity touches two schema locations; a
  contributor must remember the re-export step, and the boundary between
  "shared" and "backend-only" schemas must be enforced in review.
- **Revisit when:** we decide to publish `aide-schemas` or `aide-sdk` to
  an external index on a separate cadence (requires versioning and CI
  for that package), or when a server-only concern starts accreting in
  `aide-schemas` (a signal to split it back out).
