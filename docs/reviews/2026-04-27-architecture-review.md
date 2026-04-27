# AIDE Metastore — Architecture Review

**Date:** 2026-04-27
**Branch:** `worktree-arch_test` (off `main` @ `71e9139`)
**Scope:** `backend/`, `schemas/`, `sdk/`, `crawler/`, tests, migrations, ADRs

---

## 1. Summary

AIDE Metastore v2 is a centralized metastore for managing metadata across heterogeneous systems (RDBMS, Kafka, S3/GCS, SFTP, Hive). Contract-first approach: declaration → schema versioning → ETL pre-flight compatibility checks.

**Verdict:** the architecture is **mature and disciplined**. The backend is ready for product growth. Before production launch, operational gaps must be closed (CI/CD, health/metrics, security policies) and a UI must be built (frontend has not started).

| Aspect | Score | Comment |
|--------|-------|---------|
| Layered architecture | 9/10 | Router → Service → UoW → Repository → Model — no violations |
| Domain model | 9/10 | Polymorphism, versioning, soft-delete, audit, optimistic lock |
| Tests | 8/10 | 81 files, transactional fixtures, 4 models without repo tests |
| Documentation | 9/10 | 18 ADRs, phase specs/plans, ETL guide, ER diagram |
| Production readiness | 6/10 | Auth + observability OK, no CI/CD, no health/metrics, no policies |
| Readiness for growth | 8/10 | All specs/plans ready, frontend plan documented |

---

## 2. Architectural foundation

### 2.1 Layered model

The `Router → Service → UoW → Repository → Model` pattern is followed. No violations found (no router → repository imports, no direct commit/rollback outside UoW).

- `backend/db/uow.py` — the only transaction context manager; holds 18 repositories; auto-rollback on exception.
- `backend/services/base.py` — `GenericService[M, C, U, R]` with pre-hooks (`_pre_create`, `_pre_update`, `_pre_delete`). Optimistic locking via `row_version` (see ADR-009).
- `backend/repositories/base.py` — `BaseRepository[T]` + `SoftDeleteRepository[T]`. Correct use of `selectinload` for recursive trees (Field, TypeInstance, up to 5 levels).

### 2.2 Domain model

20 models; three centerpiece blocks:

1. **Systems and types:** `System` → `SystemKind`/`SystemFlavor` → `DataType`. YAML-driven seeding (ADR-011).
2. **Polymorphic datasets:** `Dataset` → `DatasetRdbms`/`DatasetKafka`/`DatasetSftp`/`DatasetStorage`/`DatasetHive` via joined-table inheritance (ADR-008).
3. **Lineage and contracts:**
   - `DatasetSchema` — versioned snapshot of a dataset's schema.
   - `FieldBinding` — a field within a specific schema version (types and modifiers live here).
   - `DatasetLink` — source↔target dataset link with **pins on both DatasetSchemas** (ADR-018, Phase 3).
   - `FieldLink` — identity-level field link; survives re-pin.
   - `Field.origin: {mapped, tech, deprecated}` — lifecycle state machine.

Mixin composition (`UUIDMixin`, `TimestampMixin`, `UserTrackingMixin`, `SoftDeleteMixin`, `VersionMixin`) — DRY, audit trail built in.

### 2.3 Contract engine

Bulk and per-link `compat` endpoint implemented:
- Field compatibility algorithm with cast-rule awareness.
- Separate classification of **breakage** (`error`) and **drift** (`warn`).
- Documented in `docs/integrations/etl-pre-flight.md` for worker integration.

This is the **core value feature** of the project. Cleanly decoupled from runtime lineage.

### 2.4 Error handling

`backend/core/errors.py`: 80+ codes in a single registry mapped to HTTP. `AppException` + `build_error_responses()` auto-generates OpenAPI responses with examples. Domain codes cover lineage, schemas, bindings, auth (see ADR-005).

### 2.5 SDK and Crawler

- `aide-sdk` (async httpx, JWT) — REST wrapper, resource-per-entity. `DatasetLinksResource.compat()` already shipped.
- `aide-crawler` — CLI on top of SQLAlchemy Inspector, diff vs metastore, no auto-apply. Minimal and extensible.
- Lockstep bumps of `aide-schemas` / `aide-sdk` / `aide-crawler` (0.2.0) on breaking changes — followed.

---

## 3. Code quality

### 3.1 Strengths

- Generic classes are type-safe, mypy-clean (≤10 `type: ignore`, justified by SQLAlchemy mixins).
- 25 migrations, linear history, no half-baked revisions.
- Async patterns are correct: `selectinload`, `with_polymorphic`, explicit `flush()` for server-default columns via RETURNING.
- Pydantic settings include a production guard (`_check_production_safety`) — JWT secret length validated, `*` CORS + credentials rejected.

### 3.2 Weak spots and debt markers

| Item | Where | Severity |
|------|-------|----------|
| `BaseResource.list` shadows builtin → `typing.List[X]` required | `sdk/aide_sdk/resources/base.py` | low |
| Mypy stragglers: yaml stubs, `datasets.py` type assignment | `backend/scripts/_seed_core.py`, `sdk/aide_sdk/resources/datasets.py` | low |
| Migration B downgrade unsafe once DEPRECATED fields exist | `backend/alembic/versions/*lineage_pins_b*` | medium — documented in CLAUDE.md |
| `Field.children` lazy-load — `MissingGreenlet` in tests without `selectinload` | `backend/models/field.py` | low, workaround known |
| Bulk compat — O(N) per page (one compat_report per row) | `repositories/dataset_link.py::list_with_compat_summary` | medium — flagged in ADR-018 as «revisit under load» |
| No frontend | — | UX blocker |
| No CI/CD pipeline (`.github/workflows/`) | repo root | production blocker |

### 3.3 Test coverage

81 test files, mirroring `backend/`. Transactional fixtures, no `skip`/`xfail`. Crawler/SDK tests are DB-agnostic.

**Gaps:** no `tests/repositories/` files for models `cast_rule`, `crawl_run`, `credential_ref`, `system`. Covered indirectly at the API level, but the repo layer needs filling in.

Helper duplication (`_make_system`, `_create_dataset`, `_create_field` inlined across files) — flagged in CLAUDE.md as a promotion point to `tests/conftest.py` once a 3rd copy appears.

---

## 4. Production readiness

### 4.1 What is in place

- **Observability** (ADR-015): structlog (JSON/console), request-id middleware, slow-query log with threshold.
- **Auth:** JWT HS256 + bcrypt + refresh rotation + revocation (ADR-012). 48-byte tokens, SHA256 hash stored in DB.
- **Rate limit:** slowapi by IP (login).
- **Config:** Pydantic Settings with production validators; rejects insecure defaults.
- **Errors:** machine-readable codes + deterministic HTTP responses.
- **Docker:** multi-stage Dockerfile, compose with app/db/test-db.
- **Migrations:** Alembic, convention «one model change = one migration».

### 4.2 What is missing (production blockers)

| Gap | Impact | Priority |
|-----|--------|----------|
| No CI/CD (`.github/workflows/`) | Regressions are not caught automatically | **critical** |
| No `/health`, `/ready`, `/metrics` | k8s probes impossible, ops is blind | **critical** |
| No password policy / account lockout | Brute-force exposure | high |
| No per-user rate limit | DoS / abuse | medium |
| No backup / DR plan | RPO/RTO undefined | medium |
| Single-instance PG, no HA | SPOF | medium |
| No multi-tenancy (RBAC absent — only authn, no authz) | Single-org scenarios only | depends on target audience |
| No webhooks for compat | Poll-only mode | low, documented |

### 4.3 Suggested order of closure

1. CI: `make check` + `make test-docker` in GitHub Actions on PR (1 day).
2. `/health` (DB ping) + `/metrics` (prometheus_client) (1 day).
3. Password policy + account lockout (2 days).
4. Per-user rate limit (1 day).
5. Helm chart / production compose with HA-PG (Patroni/RDS) — separate phase.

---

## 5. Architectural decisions and their maturity

| ADR | Topic | Maturity |
|-----|-------|----------|
| 001 | Layered architecture | Applied without exceptions |
| 002 | Generic base classes | Stable, extended via pre-hooks |
| 003 | Unit of Work | The only transaction path |
| 004 | Monorepo + re-export | Lockstep releases work |
| 005 | Error registry | 80+ codes, single source |
| 006 | Soft delete | **Proposed** — yet applied everywhere; promote to Accepted |
| 007 | Testing strategy | Followed, with a gap for 4 models |
| 008 | Polymorphic dataset | 5 subtypes, joined inheritance |
| 009 | Optimistic locking | `row_version` on critical entities |
| 010 | Enum as varchar | Applied (Field.origin, custom enums) |
| 011 | YAML reference seeding | Idempotent, documented |
| 012 | JWT + refresh rotation | Production-grade |
| 013 | Credential indirection | `CredentialRef` decouples secrets from metadata |
| 014 | Filter/sort contract | Unified for list endpoints |
| 015 | Observability | Foundation in place, no /metrics |
| 016 | Lineage Phase 1 | Shipped |
| 017 | Tech-field templates | Shipped |
| 018 | Schema-pinned lineage | Shipped |

**Discrepancy:** ADR-006 is `Proposed` while soft-delete is in production code everywhere. Promote to `Accepted`.

---

## 6. Bottom line

The backend is **architecturally ready** for growth: clean layered model, well-thought-out domain, contract engine that actually works. Technical debt is low and documented.

**Before production** — close the operational quadrant: CI, health/metrics, security policies.

**In parallel** — start frontend Phase 1 (plan is ready).

See also: [`2026-04-27-roadmap-and-positioning.md`](./2026-04-27-roadmap-and-positioning.md).
