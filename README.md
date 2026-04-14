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
- **Python SDK** — `aide-sdk` async client wrapping the REST API
- **RDBMS Metadata Crawler** — `aide-crawler` CLI introspects any RDBMS via SQLAlchemy Inspector and diffs against the metastore

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

### Monorepo Layout

Four packages wired via `[tool.uv.sources]` in root `pyproject.toml`:

```
aide/
├── backend/         # FastAPI metastore (depends on aide-schemas)
│   ├── api/v1/          # REST endpoints (FastAPI routers)
│   ├── core/            # Config, logging, security, error codes
│   ├── db/              # Session management, Unit of Work
│   ├── models/          # SQLAlchemy ORM models
│   ├── repositories/    # Database access layer
│   ├── schemas/         # Re-exports from aide-schemas
│   ├── services/        # Business logic layer
│   ├── scripts/         # Utility scripts (superuser init)
│   └── alembic/         # Database migrations
├── schemas/         # aide-schemas — shared Pydantic DTOs (zero backend deps)
├── sdk/             # aide-sdk — async REST client (httpx, JWT auth)
└── crawler/         # aide-crawler — RDBMS metadata crawler CLI
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
| `/type-instances` | Parameterized type instances per field binding |
| `/crawl-runs` | Crawler run audit log (status, config, summary) |

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

### Seeding data types

Pre-load PG14 built-in data types (plus `SystemKind` + `SystemFlavor` rows) from the curated YAML. Run inside the compose network so the `db` hostname resolves:

```sh
make seed-data-types
```

Or run the script directly for other flavors / `--dry-run`:

```sh
docker compose run --rm app python -m backend.scripts.seed_data_types \
  --file backend/scripts/data/postgres14.yaml --dry-run
```

The script is idempotent — re-running after editing the YAML applies only diffs. Removing a type from YAML does NOT delete the row (protects existing `TypeInstance` FKs). New flavors get their own YAML under `backend/scripts/data/`.

## Testing

```sh
# Backend tests in Docker (recommended)
make test-docker

# Run specific tests
make test-docker PYTEST_ARGS="tests/api/test_login.py"

# Run by keyword
make test-docker PYTEST_ARGS="-k 'test_create_user_success' -vv"

# Rebuild test image after dependency changes
make build-test

# SDK tests (no DB needed)
cd sdk && uv run pytest tests/

# Crawler tests (no DB needed)
cd crawler && uv run pytest tests/
```

## RDBMS Crawler

`aide-crawler` introspects a target RDBMS via SQLAlchemy Inspector, normalizes metadata, diffs against the metastore, and produces a report. No auto-apply — human decides what to apply.

### Install

```sh
cd crawler
uv sync
```

### Usage

```sh
# Full crawl pipeline (system must be registered in metastore)
uv run aide-crawler crawl \
    --system-code postgres-prod \
    --connection-url "postgresql+psycopg://user:pass@host:5432/db" \
    --metastore-url http://localhost:8001 \
    --metastore-user crawler@aide \
    --metastore-password <pwd>

# Crawl a single table (minimal test)
uv run aide-crawler crawl --system-code postgres-prod --tables public.users

# Narrow to specific schemas
uv run aide-crawler crawl --system-code postgres-prod --schemas public,analytics

# Output diff as JSON
uv run aide-crawler crawl --system-code postgres-prod --format json -o report.json

# Inspect-only (no metastore interaction, for debugging)
uv run aide-crawler inspect --connection-url "postgresql+psycopg://..." --tables public.users
```

### CLI flags

| Flag | Purpose |
|---|---|
| `--system-code` | System registered in metastore (required for `crawl`) |
| `--connection-url` | SQLAlchemy URL for target RDBMS (or env `AIDE_CRAWLER_CONNECTION_URL`) |
| `--tables` | Include only these tables — `schema.table` or `table` (comma-separated) |
| `--exclude-tables` | Skip these tables |
| `--schemas` | Include only these schemas |
| `--exclude-schemas` | Skip these schemas |
| `--format text\|json` | Report format (default: text) |
| `-o <file>` | Write report to file (default: stdout) |

### Prerequisites

- Target system registered in metastore (`POST /api/v1/systems`)
- `DataType` records seeded for the system's flavor — crawler fails fast if missing
- Network access from crawler to both target RDBMS and metastore API

## Data Model Visualization

Export is available in `docs/AIDE_data_model.json` (ChartDB format).

To view it:
```sh
docker run -p 8003:80 ghcr.io/chartdb/chartdb:latest
```
Then import the JSON file in the UI.
