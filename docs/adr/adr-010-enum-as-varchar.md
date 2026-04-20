# ADR-010: Enum Fields as `VARCHAR`, not PostgreSQL `ENUM`

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

Several AIDE entities carry enum-like fields: `CastRule.safety`
(`implicit | safe | unsafe`), `CrawlRun.status`
(`running | completed | failed`), `User.user_type`
(`regular | technical`), and more will appear as the catalogue grows.

PostgreSQL supports a native `CREATE TYPE ... AS ENUM` type which
enforces the value set at the database level. It is the first reflex
of anyone reading "the field takes one of four values" in a schema —
but it carries a set of operational properties that hurt us more than
they help.

The project actually started with one native PG enum
(`castsafety` → `CastRule.safety`). Migration
[`f6a7b8c9d0e1_convert_castsafety_enum_to_varchar.py`](../../backend/alembic/versions/f6a7b8c9d0e1_convert_castsafety_enum_to_varchar.py)
removed it in favour of `VARCHAR(20)` with application-level
validation — this ADR ratifies that reversal as a standing convention
for every enum-like field in the codebase.

The convention must answer:

- Where does the value set live, and how is it enforced?
- How do we rename, add, or remove an enum value?
- How do we surface an invalid value to clients?
- How do schemas, models, and the SDK stay in sync on the set?

## 2. Options Considered

### Option A: Python `str, Enum` in models/schemas + `VARCHAR(N)` in PostgreSQL — **chosen**

- Define a `class CastSafety(str, enum.Enum): …` next to the model.
- Store the column as `String(20)` (or similar small VARCHAR).
- Use the same enum in the Pydantic schema so validation at the edge
  (`Pydantic → 422`) catches unknown values before the service runs.
- The service layer uses the enum's `.value` strings when assigning or
  comparing.

| Dimension | Assessment |
|-----------|------------|
| Migration cost to add a value | **None** — just update the Python enum |
| Migration cost to rename a value | **Low** — one UPDATE statement on existing rows |
| Migration cost to remove a value | **Low** — one UPDATE/delete statement |
| Enforcement | **Application-side** (Pydantic + enum membership check) |
| Runtime overhead | **None** — plain varchar |
| DB-level safety net | **None** — a bug that bypasses validation can write garbage |

**Pros:**

- Adding, renaming, or removing a value is a plain code + data change.
  No `ALTER TYPE` inside a transaction (PG does not allow it), no
  downtime, no multi-step migration.
- The value set is owned by the application — the single source of
  truth is the Python enum class. Pydantic rejects unknown values at
  the API boundary, so the database sees only validated strings.
- Tests, fixtures, and SDK code all reference the enum by name
  (`CastSafety.SAFE.value`) — IDE auto-complete and mypy cover the
  codebase.
- The column type is a trivial `VARCHAR(N)` — no special driver
  support, no dialect gymnastics, portable to any engine.

**Cons:**

- The database cannot reject a non-enum value written by a tool that
  bypasses the app (direct SQL, a buggy test, a rogue migration).
- The value set is duplicated in the Python enum, Pydantic schema (via
  the same enum reference), and any documentation — refactoring a
  name requires a cross-repo sweep.
- `SELECT status FROM crawl_runs` returns `str`, not a tagged enum
  type — downstream SQL that wants to pattern-match must know the
  value set.

### Option B: Native `CREATE TYPE ... AS ENUM` (SQLAlchemy `postgresql.ENUM`)

The "textbook" Postgres approach.

**Pros:** the database enforces the value set; reads return a typed
`enum`; the schema is self-documenting in `\dT`.
**Cons:** this is exactly what we tried and reversed. Concretely:

- `ALTER TYPE foo ADD VALUE 'bar'` cannot run inside a transaction
  in PG ≤ 11, and still has transactional quirks through PG 16. Our
  migrations run inside transactions by default; working around this
  on every enum change is a chore.
- Values cannot be removed from a native enum at all — the only
  option is to create a new type, convert the column, drop the old
  type. That is three statements in a specific order, and any view or
  default that referenced the old type breaks.
- Renaming a value is `ALTER TYPE ... RENAME VALUE` (only since PG
  10) and carries the same transactional caveats.
- Case-sensitivity surprises: the historic enum stored
  `IMPLICIT/SAFE/UNSAFE` uppercase; the app expected
  `implicit/safe/unsafe` lowercase. The fix was
  `ALTER COLUMN safety TYPE varchar(20) USING lower(safety::text)` —
  which is also what we did to exit the native enum.

### Option C: Separate `<entity>_status` lookup table

A normalized reference table per enum, joined by FK.

**Pros:** maximum flexibility — extra metadata per value, runtime
editability through admin UI.
**Cons:** turns a plain column read into a join for every query;
over-engineers a 2–4 value set; migration to add/remove values still
requires FK integrity handling.

### Option D: `CHECK` constraint on a `VARCHAR`

`status VARCHAR(20) CHECK (status IN ('running', 'completed',
'failed'))`.

**Pros:** DB-level enforcement without the PG enum's rename/remove
constraints; the check is just SQL.
**Cons:** a schema change on every set change (drop + add constraint);
the value list is duplicated in two places (Python + DDL), and they
must agree.

## 3. Trade-off Analysis

The tension is **DB-level enforcement vs. migration flexibility**. A
metadata catalogue evolves its value sets continuously — new cast
safety levels, new crawl statuses, new user types — and the cost of a
single Postgres-enum migration is already visible in our history.
Options B and D buy enforcement at the price of every future schema
change being a ceremony. Option A pays the cost upfront (validation
lives in the app, not the DB) and then makes every subsequent change
cheap.

We accept the loss of DB-level enforcement as a reasonable trade
because every write path goes through Pydantic validation (ADR-001
ensures services do not bypass it; ADR-007 ensures tests cover the
paths).

## 4. Recommendation

Adopt Option A. Use Python `str, enum.Enum` for every enum-like
field; store the column as `VARCHAR(N)` (or `String(N)` in SQLAlchemy);
share the enum between model, schema, and SDK; enforce the value set
through Pydantic.

## 5. Implementation Notes

### Model pattern

```python
# backend/models/cast_rule.py
import enum

class CastSafety(str, enum.Enum):
    IMPLICIT = "implicit"
    SAFE = "safe"
    UNSAFE = "unsafe"

class CastRule(Base, MetaDataMixin):
    __tablename__ = "cast_rules"
    safety: Mapped[str] = mapped_column(String(20), nullable=False)
```

Rules:

- Inherit from `str, enum.Enum` — the mixin lets instances compare
  directly to plain strings (`obj.safety == CastSafety.SAFE` works
  whether the ORM returned the enum or its value).
- Values are **lowercase**. The historical `UPPER` values in
  `CastSafety` were normalised to lowercase during the
  `f6a7b8c9d0e1` migration; every new enum adopts lowercase from the
  start.
- Pick a `String(N)` size that comfortably fits the longest current
  value with room to grow — `String(20)` is the default across the
  codebase.
- The column type annotation is `Mapped[str]`, not `Mapped[CastSafety]`.
  SQLAlchemy treats the column as `str`; the enum is purely an
  application-level alphabet.

### Schema pattern

```python
# schemas/aide_schemas/cast_rule.py
class CastSafety(str, enum.Enum):
    IMPLICIT = "implicit"
    SAFE = "safe"
    UNSAFE = "unsafe"

class CastRuleCreate(BaseModel):
    safety: CastSafety
```

Pydantic enforces membership. On an unknown value, the client receives
`422 UNPROCESSABLE_ENTITY` with the offending field path — no service
code runs.

### Where the canonical enum lives

`aide_schemas` cannot import from `backend` (ADR-004 dependency
direction: `aide-schemas ← backend`). The shared package is therefore
the **canonical location** for any enum that appears on the wire.

The current codebase has three enums — `CastSafety`, `CrawlStatus`,
`UserType` — each defined **twice**, once in `backend/models/<entity>.py`
and once in `schemas/aide_schemas/<entity>.py`, with identical members
and values. This duplication is a pragmatic workaround and a known
maintenance risk: adding a member in one place without the other
silently breaks round-trips.

Going forward:

- **New enum:** define it once in `schemas/aide_schemas/<entity>.py`;
  import it from there into `backend/models/<entity>.py`. Backend
  depends on `aide-schemas`, so the import is one-way and legal.
- **Existing duplicated enum:** when touching it for any reason, take
  the opportunity to collapse the model-side definition to
  `from aide_schemas.<entity> import <Enum> as <Enum>` and delete the
  duplicate body.

Do not define the enum only in `backend/models/…` and reference it
from `aide_schemas` — that would flip the dependency direction and
break the SDK / crawler builds.

### Default values

When a column has a default enum value, set it from the enum's
`.value` to avoid SQLAlchemy trying to serialize the enum object:

```python
user_type: Mapped[str] = mapped_column(
    String(20),
    default=UserType.REGULAR.value,
    nullable=False,
    index=True,
)
```

(See [`backend/models/user.py:31`](../../backend/models/user.py:31).)

### Changing an enum

Changes are driven from the Python enum, not the database.

**Add a value:**
1. Add the member to the enum class.
2. Update any Pydantic schema that uses the enum (usually none — the
   class reference picks it up).
3. No migration needed — the column already accepts any string up
   to its length.

**Rename a value:**
1. Rename the enum member (and its `.value` if the wire label
   changes).
2. Write a one-step Alembic migration:
   ```python
   op.execute(
       "UPDATE cast_rules SET safety = 'new_label' "
       "WHERE safety = 'old_label'"
   )
   ```
3. If an SDK client persists the old label in its own store, plan a
   release boundary.

**Remove a value:**
1. Remove the enum member.
2. Write a migration that either moves remaining rows to a surviving
   label or deletes them, per domain semantics.
3. Consider the client compatibility: removing a label is a breaking
   change on the wire.

### Why not a `CHECK` constraint on top of the `VARCHAR`?

We do not add a `CHECK (foo IN (...))` constraint. Every rename/remove
would require a drop-and-recreate of the constraint, which defeats the
purpose of the choice. The Pydantic boundary is the enforcement seam.

### Testing

- API tests (ADR-007) cover the happy path (valid value accepted) and
  the 422 path (invalid value rejected by Pydantic).
- Service unit tests use `EnumClass.VALUE.value` strings directly when
  constructing fixtures — never a hardcoded string literal, so a
  rename breaks the test file instead of silently writing the old
  value.

### The historic migration (for context)

The migration chain includes exactly one enum conversion,
[`f6a7b8c9d0e1_convert_castsafety_enum_to_varchar.py`](../../backend/alembic/versions/f6a7b8c9d0e1_convert_castsafety_enum_to_varchar.py).
It:

1. `ALTER TABLE cast_rules ALTER COLUMN safety TYPE varchar(20) USING
   lower(safety::text)` — drops the enum type from the column while
   normalising the values to lowercase.
2. `DROP TYPE IF EXISTS castsafety` — removes the dead type.

New ADR-010 changes do not require any equivalent migration; the point
of the policy is that we never adopt a native PG enum in the first
place.

## 6. Consequences

- **Easier:** enum evolution (add / rename / remove a value) is a
  code + data change without a schema surgery; every new enum starts
  lowercase and short.
- **Harder:** bug-by-bypass possible — a direct SQL `UPDATE` can
  write a value the app would reject. Treat direct DB writes in
  production as a privileged operation and guard with code review.
- **Revisit when:** we integrate a non-Python writer (e.g. a service
  in another language) whose validation we cannot trust, or when the
  value set grows past ~20 and begins to need per-value metadata (at
  which point Option C — a reference table — becomes the better fit).
