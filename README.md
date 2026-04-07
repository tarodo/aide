# AIDE Metastore v2

### Contract-Driven Metadata Management for Enterprise Data Platforms

## Overview

**AIDE Metastore v2** is a centralized metadata management system that acts as the **single source of truth** for systems, datasets, schemas, and type mappings across heterogeneous data environments.

It provides a **contract-first, API-driven layer** for describing and governing data infrastructure metadata — not execution, but declarative configuration.

## Core Capabilities

- **Centralized Metadata Registry** — Manage systems, datasets, and schemas through a unified REST API
- **Schema Versioning** — Track dataset schema evolution with full version history
- **Parametric Type System** — Define data types with JSON Schema parameters and Jinja2 render templates
- **Cross-System Casting Rules** — Standardize type mapping between RDBMS, Kafka, S3, Hive, and SFTP
- **Polymorphic Datasets** — Unified model for 5 source types: RDBMS, Kafka, Cloud Storage, SFTP, Hive
- **PII Tagging** — Tag fields with PII markers for governance awareness

## Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.13 |
| **Framework** | FastAPI (async) |
| **ORM** | SQLAlchemy 2.0 (async) |
| **Database** | PostgreSQL 17 |
| **Auth** | JWT (HS256) + bcrypt |
| **Logging** | structlog (JSON / console) |
| **Package Manager** | uv |
| **Deployment** | Docker + docker-compose |

## Architecture

AIDE Metastore v2 follows a **Service-Repository-UoW** architecture:

- **Service-Repository Pattern** — Business logic isolated from persistence layer
- **Generic CRUD Layer** — `GenericService` / `BaseRepository` with type generics
- **Unit of Work (UoW)** — Transaction boundary per business operation
- **Pydantic + SQLAlchemy 2.0** — Declarative ORM + strict data validation
- **Dependency Injection** — FastAPI `Depends()`-based composition
- **Async-first** — All DB and API operations are non-blocking
- **Centralized Error Handling** — Machine-readable error codes with HTTP mapping

### Folder Layout

```
backend/
├── api/v1/          # REST endpoints (FastAPI routers)
├── core/            # Config, logging, security, error codes
├── db/              # Session management, Unit of Work
├── models/          # SQLAlchemy ORM models
├── repositories/    # Database access layer
├── schemas/         # Pydantic DTOs (Create/Read/Update)
├── services/        # Business logic layer
├── scripts/         # Utility scripts (superuser init)
└── alembic/         # Database migrations
```

## API Endpoints

All endpoints are under `/api/v1`:

| Endpoint | Entity |
|---|---|
| `/users` | User management |
| `/login` | Authentication (OAuth2 Password Flow) |
| `/system-kinds` | System categories (RDBMS, MESSAGE_QUEUE, ...) |
| `/system-flavors` | Technologies (PostgreSQL, Kafka, ...) |
| `/data-types` | Native data types per flavor |
| `/credential-refs` | External credential references |
| `/systems` | Data platforms |
| `/datasets` | Data assets (polymorphic: rdbms/kafka/storage/sftp/hive) |
| `/fields` | Logical fields within datasets |
| `/dataset-schemas` | Versioned dataset schemas |
| `/field-bindings` | Field-to-schema-version mappings with type info |
| `/cast-rules` | Type casting rules between data types |

## Quick Start

### Using Make

**Start all services:**
```sh
make up
```
Builds and starts backend + PostgreSQL, runs migrations, and creates an initial superuser.

**Stop services:**
```sh
make stop
```

**Other commands:**
```sh
make format          # Auto-format code (black + ruff)
make check           # Run linting and type checks (ruff + black + mypy)
make alembic-gen MSG="migration message"  # Generate new migration
make alembic-head    # Apply pending migrations
```

## Testing

```sh
# Run all tests in Docker (recommended)
make test-docker

# Run specific tests
make test-docker PYTEST_ARGS="tests/api/test_login.py"

# Run by keyword
make test-docker PYTEST_ARGS="-k 'test_create_user_success' -vv"

# Rebuild test image after dependency changes
make build-test
```

## Data Model Visualization

Export is available in `docs/AIDE_data_model.json` (ChartDB format).

To view it:
```sh
docker run -p 8003:80 ghcr.io/chartdb/chartdb:latest
```
Then import the JSON file in the UI.
