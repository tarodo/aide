# ADR: Current State Analysis of the AIDE Metastore v2 Project

**Status:** Proposed
**Date:** 2026-04-06
**Author:** Architecture Review

---

## 1. Project Overview

**AIDE Metastore v2** is a centralized metadata management system for enterprise data platforms. It provides a contract-first, API-driven layer for describing systems, datasets, schemas, and type conversion rules.

### Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.13.9 |
| Framework | FastAPI (>=0.120.4) |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 17 |
| Authentication | JWT (HS256) + bcrypt |
| Logging | structlog (JSON/console) |
| Package Manager | uv |
| Containerization | Docker + docker-compose |

### Architectural Patterns

- **Service-Repository** — business logic is isolated from the persistence layer
- **Unit of Work (UoW)** — transactional boundary at the request level
- **Generic CRUD** — `GenericService`/`BaseRepository` with TypeVar generics
- **Dependency Injection** — via FastAPI `Depends()`
- **Async-first** — all operations are non-blocking

---

## 2. Codebase Metrics

| Metric | Value |
|--------|-------|
| Python files (backend) | ~60 |
| Lines of code (backend) | ~2,300 |
| Domain entities | 13 |
| API routers | 13 |
| Services | 14 (GenericService + 13 domain) |
| Repositories | 14 (BaseRepository + 13 domain) |
| Pydantic schemas | 13 modules (Create/Read/Update per entity) |
| Alembic migrations | 8 |
| Test files | 35 |
| Dependencies (production) | 11 |
| Dependencies (dev) | 9 |

---

## 3. Application Architecture

### Layers and Data Flow

```
HTTP Request
    |
    v
[API Layer]          backend/api/v1/*.py        — routing, validation, authorization
    |
    v
[Service Layer]      backend/services/*.py      — business logic, pre-create/pre-update hooks
    |
    v
[Unit of Work]       backend/db/uow.py          — transaction management
    |
    v
[Repository Layer]   backend/repositories/*.py   — data access, CRUD
    |
    v
[ORM Models]         backend/models/*.py         — SQLAlchemy models
    |
    v
[PostgreSQL]
```

### Key Components

**GenericService** (`backend/services/base.py`):
- Typed CRUD with TypeVar generics
- `_pre_create()` / `_pre_update()` hooks for validation in domain services
- Automatic population of `created_by` / `updated_by`
- Pagination via `Page[T]`

**UnitOfWork** (`backend/db/uow.py`):
- Async context manager with automatic commit/rollback
- All repositories accessible as attributes (`uow.users`, `uow.datasets`, etc.)
- One transaction per business operation

**CRUD Router** (`backend/api/v1/utils/crud_router.py`):
- Standard CRUD endpoint generator
- Reduces boilerplate for typical entities

---

## 4. Authentication and Authorization

- **JWT tokens** with HS256 algorithm, 30-minute lifetime
- **OAuth2 Password Flow** via `/api/v1/login`
- **Two access levels:** `user` (read) and `superuser` (full CRUD)
- **Dependency-based authorization:** `get_current_user()` / `get_current_superuser()`
- **Passwords:** hashed via bcrypt

---

## 5. Error Handling

Centralized error registry (`backend/core/errors.py`):

- 25+ predefined error codes
- Each code maps to an HTTP status and detail message
- Global exception handler converts `AppException` to JSON
- `build_error_responses()` generates OpenAPI documentation for errors

---

## 6. Logging and Monitoring

- **structlog** — structured logging with JSON (production) and console (dev) renderers
- **Request ID** — automatic binding of `X-Request-ID` to each request
- **Contextual data:** method, path, client IP, status code, process time (ms)
- Prometheus and monitoring are **not implemented** (mentioned only in README)

---

## 7. Infrastructure

### Docker
- `docker-compose.yml`: app, db (PostgreSQL 17), db-test
- `Dockerfile`: dev target only with hot-reload (uvicorn --reload)
- Automatic migrations and superuser creation on startup

### Code Quality
- **Pre-commit hooks:** ruff (linter), black (formatting), mypy (types), pytest (tests)
- **Makefile:** `make up`, `make test-docker`, `make format`, `make check`

### Testing
- Session-scoped migrations via Alembic
- Per-test transactional fixtures with auto-rollback
- Separate database for tests (PostgreSQL on port 5433)

---

## 8. Identified Issues

### CRITICAL

| # | Issue | File | Description |
|---|-------|------|-------------|
| 1 | JWT Secret is hardcoded | `backend/core/settings.py:25` | Default value `"a_super_secret_key_that_should_be_in_env"`. In production, this allows forging any token. |
| 2 | CORS is open to all | `backend/core/settings.py:16` | `CORS_ORIGINS = ["*"]` allows requests from any domain. Risk of CSRF attacks. |

### HIGH PRIORITY

| # | Issue | Description |
|---|-------|-------------|
| 3 | No CI/CD pipeline | Only local pre-commit hooks. No GitHub Actions or equivalent. Code can reach main without checks. |
| 4 | README diverges from code | Redis and Prometheus are claimed in README but not implemented. Misleads new developers. |
| 5 | No production Dockerfile | Dev target only. No multi-stage build, image size optimization, non-root user. |

### MEDIUM PRIORITY

| # | Issue | Description |
|---|-------|-------------|
| 6 | `created_by`/`updated_by` without FK | No foreign key to the `users` table. Cannot guarantee referential integrity for auditing. |
| 7 | No health check endpoint | Missing `/health` or `/readiness` for orchestrator (Kubernetes, ECS). |
| 8 | No rate limiting | No protection against DDoS/brute-force on `/login`. |
| 9 | Duplicate PostgreSQL drivers | Both psycopg, psycopg2-binary, and asyncpg are installed simultaneously. |

### LOW PRIORITY

| # | Issue | Description |
|---|-------|-------------|
| 10 | No soft delete | Record deletion is irreversible. No `deleted_at` field for soft deletion. |
| 11 | No API versioning strategy | Only `/api/v1`, no plan for v2 migration. |
| 12 | No OpenAPI metadata | Missing tag descriptions and general API information. |

---

## 9. Strengths

1. **Clean architecture** — clear layer separation with minimal coupling
2. **GenericService** — effective CRUD logic reuse through generics
3. **Async-first** — all operations are non-blocking, ready for load
4. **Centralized error handling** — uniform responses, auto-generated OpenAPI documentation
5. **Good documentation** — C4 diagrams, ADR, developer guides, data model docs
6. **Structured logging** — request ID tracking, JSON format for production
7. **Polymorphic datasets** — flexible model for 5 data source types
8. **Parametric type system** — powerful mechanism for cross-system type mapping

---

## 10. Summary

The project has a **solid architectural foundation** but is at an **early stage** of development. The main risks are related to security (JWT secret, CORS) and the lack of production infrastructure (CI/CD, Docker, monitoring). Before adding new functionality, it is necessary to address critical security issues and set up the pipeline.
