# AIDE Metastore

## Conventions

### Enum fields

Enum-like fields are stored as `varchar` in PostgreSQL. Validation happens at the application level via Python `str, enum.Enum` and Pydantic schemas. Do **not** use PostgreSQL native `CREATE TYPE ... AS ENUM`.

**Pattern:**
```python
# models/example.py
class MyStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

status: Mapped[str] = mapped_column(String(20), nullable=False)

# schemas/example.py — use the same enum for Pydantic validation
status: MyStatus
```

**Rationale:** Native PG enums require painful migrations (`ALTER TYPE` cannot run inside a transaction, values cannot be removed). String columns with app-level validation are simpler to evolve.

### Formatting

Run `make format` after code changes. This runs `black` + `ruff check --fix`. Fix any remaining ruff errors manually.

### Testing

Tests run via `make test-docker` in Docker, not locally.
