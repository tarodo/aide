# AIDE Metastore v2

### **Contract-Driven Metadata Management for Enterprise Data Platforms**


## Overview

**AIDE Metastore v2** is a centralized metadata management system that acts as the **single source of truth** for datasets, schemas, pipelines, and type systems across heterogeneous data environments.

Unlike traditional ETL/ELT engines, it focuses on **declarative configuration and orchestration**, not execution — providing a **contract-first, API-driven layer** for governing and automating data integration at scale.

## Core Capabilities

* **Centralized Metadata Registry** – Manage systems, datasets, and schemas through a unified API
* **Schema Versioning** – Track schema evolution with full version history and compatibility checks
* **Type System & Casting Rules** – Standardize type mapping across RDBMS, Kafka, S3, and more
* **Pipeline Contracts** – Declarative source-to-target data flow definitions
* **Quality & Governance** – SLA monitoring, PII masking, and lineage tracking

## Tech Stack

| Layer          | Technology                        |
| -------------- | --------------------------------- |
| **Backend**    | Python 3.13 + FastAPI             |
| **ORM / DB**   | SQLAlchemy 2.0 + PostgreSQL       |
| **Cache**      | Redis                             |
| **Auth**       | JWT-based with role permissions   |
| **Monitoring** | Prometheus + structured JSON logs |
| **Deployment** | Docker / Kubernetes-ready         |

## Architecture Principles

AIDE Metastore v2 follows a **service–repository architecture** to ensure modularity, scalability, and clear separation of concerns.

**Core principles:**

* **Service–Repository Pattern** – Business logic isolated from persistence layer
* **Generic CRUD Layer** – `BaseService` / `BaseRepository` with type generics
* **Unit of Work (UoW)** – Transaction boundary per API request
* **Pydantic + SQLAlchemy 2.0** – Declarative ORM + strict data validation
* **Dependency Injection** – FastAPI `Depends()`-based composition
* **Async-first Design** – All DB and API operations are asynchronous
* **Schema-first Modeling** – Database schema versioned under `/docs`
* **Domain-Oriented Structure** – Entities → Services → API

**Folder layout:**

```
aide/
├── api/            # REST endpoints (FastAPI routers)
├── core/           # Config, logging, dependencies
├── db/             # Session management, UnitOfWork
├── models/         # SQLAlchemy models
├── repositories/   # Database access layer
├── schemas/        # Pydantic DTOs
├── services/       # Business logic layer
└── tests/
```

## Success Metrics

* New table onboarding: **4h → 30min**
* Configuration errors: **−85%**
* Manual overhead: **−75%**
* Data lineage coverage: **100%**

## Vision

AIDE Metastore v2 transforms data integration into a **governed, automated, and contract-driven** discipline — reducing operational overhead, enforcing consistency, and scaling metadata management for the enterprise.

## ChartDB Model
```sh
docker run -p 8003:80 ghcr.io/chartdb/chartdb:latest
```

## Start Project

### Using Make

**Docker deployment:**
```sh
make up
```
Builds and starts all services (backend, database, Redis), runs migrations, and creates a superuser.

**Stop services:**
```sh
make stop
```

**Other useful commands:**
```sh
make format          # Auto-format code (black + ruff)
make check           # Run linting and type checks
make alembic-gen MSG="migration message"  # Generate new migration
make alembic-head    # Apply pending migrations
```

### Testing

The testing setup is optimized to avoid unnecessary Docker image rebuilds, making the test cycle fast and flexible.

**Run all tests:**
```sh
make test-docker
```

**Run specific tests or pass arguments:**

You can pass any `pytest` arguments via the `PYTEST_ARGS` variable.
```sh
# Run tests in a specific file
make test-docker PYTEST_ARGS="tests/api/test_login.py"

# Run tests by keyword matching
make test-docker PYTEST_ARGS="-k 'test_create_user_success' -vv"

# Rebuild the test image if dependencies have changed (e.g., Dockerfile or pyproject.toml changed)
make build-test
```
