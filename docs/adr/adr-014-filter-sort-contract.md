# ADR-014: Filter and Sort Contract for List Endpoints

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

Every collection-style endpoint in AIDE needs the same shape of query
string:

- Paginate (`page`, `size`).
- Filter by one or more fields, possibly with a comparison operator
  (`created_at >= 2026-01-01`, `code LIKE '%prod%'`, `flavor_id IN
  (...)`).
- Sort by one or more fields in either direction.

Three things must be true for the contract to survive fifteen entities
and a growing SDK:

1. **Stability.** The SDK serialises URLs from Python values; a format
   change breaks every client simultaneously.
2. **Safety.** Unknown filter fields, free-form `ORDER BY`, or
   unescaped `LIKE` arguments turn list endpoints into discovery
   surfaces (information disclosure) or injection surfaces. A list
   endpoint must reject anything it does not explicitly permit.
3. **Uniformity.** A developer reading one router must be able to
   predict how every other router handles the same concerns. Each
   endpoint re-deriving its own query-parsing logic is the surest
   path to drift.

The question is: what query-string shape do we commit to, and how do
we wire it through the layers so that the router, the service, and
the repository all speak the same language?

## 2. Options Considered

### Option A: Pydantic filter model + hyphen-prefix sort + operator suffix on field names — **chosen**

- **Sort.** A single query parameter `sort` holding a comma-separated
  list of field names. A leading `-` flips the direction to DESC.
  `sort=-created_at,code` means "ORDER BY created_at DESC, code ASC".
  An explicit per-entity **allow-list** (`SYSTEM_SORTABLE = {"code",
  "name", ...}` in `backend/schemas/filters.py`) is consulted; an
  unknown field raises HTTP 422 at dependency time.
- **Filter.** One **Pydantic filter model per entity**
  (`SystemFilter(BaseFilter)`) declares the allowed fields as typed
  optional attributes. `BaseFilter` enforces
  `model_config = ConfigDict(extra="forbid")`, so an unknown query
  parameter produces a 422 automatically — no allow-list code to
  maintain. Operators beyond equality are expressed as a **suffix
  on the field name**: `created_at__gte`, `name__like`, `kind__in`.
  The dependency parses the suffix, produces a `FilterSpec(field,
  op, value)`, and passes it down.
- **Wiring.** A factory
  `get_filter_sort_dependency(filter_model, sortable_fields,
  default_sort)` returns a FastAPI dependency that combines
  pagination, filters, and sort into a single `FilterSortParams`
  object, which routers forward to services unchanged.
- **Application.** `BaseRepository._apply_filters` /
  `_apply_sort` (ADR-002) translate `FilterSpec` and
  `[(field, desc)]` tuples into SQLAlchemy `where` / `order_by`
  clauses, with `LIKE` arguments escaped and rendered as `ILIKE
  '%escaped%'`.

| Dimension | Assessment |
|-----------|------------|
| Stability | **High** — URLs are short, grammar is fixed per entity |
| Safety | **High** — `extra="forbid"` + sort allow-list + LIKE escaping |
| Uniformity | **High** — every entity uses the same factory |
| Expressiveness | **Medium** — operators cover the common cases; complex predicates still require custom endpoints |

**Pros:**

- The entire grammar lives in one file per entity
  ([`backend/schemas/filters.py`](../../backend/schemas/filters.py))
  and one shared dependency factory
  ([`backend/api/filter_sort.py`](../../backend/api/filter_sort.py)).
  No router writes its own parser.
- `extra="forbid"` gives us a whitelist for *filters* for free — no
  set of allowed filter keys to maintain; a typo in a query parameter
  is a 422, not a silent fallback to "no filter".
- The hyphen-prefix sort notation is compact, order-preserving, and
  self-describing. Adding DESC to a field is a one-character change
  (`sort=code` → `sort=-code`).
- The `__suffix` operator notation keeps one query parameter per
  predicate, which is friendly to HTML forms, command-line curl, and
  programmatic URL builders. No bracket-escaping (`created_at[gte]`)
  or JSON-in-querystring.
- `LIKE` values are escaped inside the repository
  (`_apply_filters` in `BaseRepository`) — a user-supplied `%` or
  `_` does not become a wildcard. This keeps the security-relevant
  logic in one place.

**Cons:**

- The operator alphabet is finite today (`eq, gt, gte, lt, lte, in,
  like`). Adding an operator is a code change (the `FilterOp` enum
  plus the dispatcher in `_apply_filters`).
- Compound predicates (`A AND (B OR C)`) are not expressible; an
  endpoint that needs them has to expose a dedicated query endpoint.
- The sort allow-list lives *separately* from the filter model —
  two sources of truth per entity to keep in sync.

### Option B: JSON-in-query-string (`q={"and":[{"field":"code","op":"eq","value":"x"}]}`)

A single opaque `q` parameter carrying a JSON-encoded predicate tree.

**Pros:** arbitrary expressive power; one parameter.
**Cons:** URLs stop being inspectable; `curl` testing becomes painful;
SDK clients have to serialise the tree; the surface to validate
against an allow-list is much larger; debugging a 400 requires
decoding the JSON and cross-referencing the schema.

### Option C: GraphQL / OData-style `$filter`

Adopt a mini query language.

**Pros:** industry-standard (if OData); very expressive.
**Cons:** non-trivial grammar + parser to maintain; massive surface
for injection / validation bugs; far beyond the expressive needs of
the metadata catalogue.

### Option D: A bag of ad-hoc query parameters per endpoint

Each router declares the `?code=…&flavor_id=…` parameters it
happens to need; a new parameter is a code change on that specific
endpoint.

**Pros:** minimal shared machinery.
**Cons:** each endpoint diverges; operator support (gte, in) is
reimplemented or refused per endpoint; sort parsing gets copy-pasted
and drifts; the SDK's type for `list_systems(...)` differs in shape
from `list_datasets(...)` for no good reason.

### Option E: Separate `filter[field]=value` / `sort[field]=asc`
bracket notation (JSON:API-ish)

Spec-conformant with JSON:API's query language.

**Pros:** a well-known spec; libraries exist on the client side.
**Cons:** bracket notation is verbose and requires URL-encoding in
many environments (including browsers displaying the URL); the gain
over the current hyphen-prefix notation does not repay the
verbosity.

## 3. Trade-off Analysis

The axis is **expressiveness vs. cost**. Options B and C buy power
we do not need and pay with a larger security and maintenance
surface. Option D buys nothing and pays in drift. Option E is a
stylistic swap with no substantive win. Option A concentrates the
machinery in one place, keeps the URL grammar short, and makes every
list endpoint predictable.

## 4. Recommendation

Adopt Option A. Write filter models per entity; declare sort allow-
lists per entity; use the shared dependency factory and the shared
repository helpers.

## 5. Implementation Notes

### File map

| File | Role |
|------|------|
| [`backend/api/filter_sort.py`](../../backend/api/filter_sort.py) | `FilterOp`, `FilterSpec`, `BaseFilter`, `FilterSortParams`, `parse_sort`, `get_filter_sort_dependency` |
| [`backend/schemas/filters.py`](../../backend/schemas/filters.py) | Per-entity filter models (`SystemFilter`, `DatasetFilter`, …) and sort allow-lists (`SYSTEM_SORTABLE`, …) |
| [`backend/repositories/base.py`](../../backend/repositories/base.py) | `_apply_filters`, `_apply_sort` — the SQLAlchemy translation layer |
| [`backend/api/v1/utils/crud_router.py`](../../backend/api/v1/utils/crud_router.py) | Wires the dependency factory into generated list endpoints |

### Sort grammar

Query parameter: `sort` (singular).

- `sort=code` — ASC on `code`.
- `sort=-created_at` — DESC on `created_at`.
- `sort=-created_at,code` — DESC then ASC, multi-column.
- Omitted or empty — fall back to the endpoint's `default_sort`.
- Unknown field — HTTP 422 with the allowed list:
  `"Cannot sort by 'X'. Allowed: ['code', 'created_at', …]"`.

The allow-list is a plain `set[str]` passed to
`get_filter_sort_dependency`. It must be curated per entity (do
**not** blindly include `password_hash`, internal ids, or anything
the client should not learn about by inference from sort behaviour).

### Filter grammar

Each entity declares a filter model that subclasses `BaseFilter`:

```python
class SystemFilter(BaseFilter):
    code: str | None = None
    code__like: str | None = None
    name: str | None = None
    name__like: str | None = None
    is_active: bool | None = None
    flavor_id: uuid.UUID | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None
```

Rules:

- Every filterable attribute is **optional** (`| None = None`). Only
  non-`None` values appear in the resulting `FilterSortParams.filters`.
- The field name is the SQL column; the suffix after `__` is the
  operator (`eq`, `gt`, `gte`, `lt`, `lte`, `in`, `like`). `eq` is
  implicit when no suffix is present (`code: str | None` is an
  equality filter on `code`).
- Types are fully Pydantic-validated before the service runs: a bad
  UUID, a non-numeric gte, or an unparseable datetime is a 422 at
  dependency time.
- `extra="forbid"` is inherited from `BaseFilter`. Any query
  parameter that is not declared on the model (including typos like
  `cod=`) is a 422 — this is the *filter allow-list*.
- For `__in`, the value is a comma-separated string on the wire
  (`kind__in=rdbms,kafka`); the dependency splits it into a list
  before handing it to the repository.

### Operator semantics

| Operator | Wire shape | SQL translation |
|----------|-----------|-----------------|
| `eq` (implicit) | `code=foo` | `WHERE code = 'foo'` |
| `gt` | `created_at__gt=2026-01-01T00:00:00Z` | `WHERE created_at > '...'` |
| `gte` | `created_at__gte=...` | `WHERE created_at >= '...'` |
| `lt` | `created_at__lt=...` | `WHERE created_at < '...'` |
| `lte` | `created_at__lte=...` | `WHERE created_at <= '...'` |
| `in` | `kind__in=rdbms,kafka` | `WHERE kind IN ('rdbms','kafka')` |
| `like` | `name__like=prod` | `WHERE name ILIKE '%prod%' ESCAPE '\\'` (with `%`, `_`, `\\` escaped in the value) |

`like` is **case-insensitive** and **substring-anchored** — the
repository always wraps the value with leading and trailing `%`. If
you need anchored matches (`prefix%`, `%suffix`), extend the operator
set rather than smuggling wildcards through the value. `%` and `_`
in user input are escaped at the repository level
([`backend/repositories/base.py:62-66`](../../backend/repositories/base.py:62))
so they cannot become wildcards by accident.

### Dependency wiring

The factory produces a FastAPI dependency that routers consume
through `create_crud_router`:

```python
crud_router = create_crud_router(
    ...,
    filter_model=SystemFilter,
    sortable_fields=SYSTEM_SORTABLE,
    default_sort="code",
)
```

Hand-written list endpoints that do not use the CRUD router factory
can call `get_filter_sort_dependency(...)` directly and accept a
`FilterSortParams` argument.

### Flow through the layers

```
?page=1&size=20&sort=-created_at,code&created_at__gte=2026-01-01&kind__in=rdbms,kafka
        │
        ▼  FastAPI dependency
    FilterSortParams(
        page=1, size=20,
        sort=[("created_at", True), ("code", False)],
        filters={
            "kind__in":      FilterSpec("kind", IN, ["rdbms", "kafka"]),
            "created_at__gte": FilterSpec("created_at", GTE, datetime(...)),
        },
    )
        │
        ▼  Router → Service.get_paginated(uow, page, size, filters, sort)
        ▼  Service → repo.get_multi_paginated(... filters=filters, sort=sort)
        ▼  Repository._apply_filters / _apply_sort
    SELECT ... FROM systems
    WHERE deleted_at IS NULL
      AND kind IN ('rdbms','kafka')
      AND created_at >= '2026-01-01'
    ORDER BY created_at DESC, code ASC
    LIMIT 20 OFFSET 0
```

Nothing in this chain is entity-specific except the filter model and
the sort allow-list.

### Pagination defaults

`page` defaults to `1` (1-indexed), `size` defaults to `50`,
`size` is capped at `100` at the dependency level. These are
centralised in
[`backend/api/filter_sort.py:93-94`](../../backend/api/filter_sort.py:93)
and
[`backend/api/dependencies.py:26-33`](../../backend/api/dependencies.py:26)
— override them only with a concrete reason (e.g. a heavy list
endpoint that must not return 100 rows per page).

### Adding a field to filter

1. Add an optional attribute to the entity's filter model. Use the
   `__suffix` form if you want a comparison operator.
2. If the new field is also a sensible sort target, add its name to
   the entity's sort allow-list.
3. Re-run the API test for the entity's list endpoint — the test
   fixtures generally cover filter combinations.

### Adding a new operator

1. Add the enum member to `FilterOp` in `backend/api/filter_sort.py`.
2. Add the SQLAlchemy branch in `BaseRepository._apply_filters`.
3. Decide whether user input needs escaping (see the `like` case).
4. Document the operator in this ADR's operator table.

### Security rules

- Never bypass `extra="forbid"`. If an endpoint genuinely needs a
  permissive filter, add the attribute explicitly to the filter
  model.
- Never translate user input into raw SQL in a repository. Always go
  through `_apply_filters` / `_apply_sort` so the SQLAlchemy binding
  layer parametrises the value.
- Never widen the sort allow-list to include fields whose ordering
  leaks sensitive information (e.g. `hashed_password`).
- `LIKE` escaping is the repository's responsibility; do not
  re-escape at the service or router level (double-escape produces
  literal `\%` matches).

### Testing

- API tests (ADR-007) for each list endpoint cover: bare list,
  filter on each declared field, sort on each allowed field (both
  directions, multi-column), rejection of unknown filter keys
  (422), and rejection of unknown sort fields (422).
- Unit tests for the dependency factory live in
  `tests/api/test_filter_sort.py`.

### What not to do

- Do not expose a `sort=*` or `sort=any` wildcard "for convenience".
  The allow-list exists because order-by on the wrong column is both
  slow and information-disclosing.
- Do not pass unparsed query-string fragments into a service. The
  service must see a typed `FilterSortParams`; a router that hands a
  service `dict[str, str]` has broken the contract.
- Do not add a `raw_filter` JSON parameter "just for this one
  endpoint". If the filter grammar is insufficient, write a
  dedicated endpoint with a named, validated payload.

## 6. Consequences

- **Easier:** every list endpoint is one factory call and two
  declarations (filter model, sort allow-list); SDK callers see a
  consistent URL shape; security properties (whitelisting, `LIKE`
  escaping) are centralised.
- **Harder:** complex predicates require either a new operator or a
  dedicated endpoint; two sources of truth per entity (filter model
  + sort allow-list) must be kept aligned.
- **Revisit when:** a credible use case for compound predicates
  (`A AND (B OR C)`) emerges across multiple entities, or when the
  operator set grows enough that expressing operators as name
  suffixes becomes noisy (at which point Option E's bracket
  notation might win on readability).
