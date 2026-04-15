# Manual crawler test

Scripts for spinning up a target PG14, seeding it, and running the crawler against it.

## Files

- `start_pg14.sh` — start PG14 container `aide-crawler-target-pg14` on port **5434**
- `seed_target.sh` — create schema `demo` with tables exercising assorted types (incl. `text[]`, `integer[]`, `jsonb`, `numeric`, `timestamptz`, FK)

Connection URL for the target DB:
```
postgresql+psycopg://crawler:crawler@localhost:5434/target
```

## Process

### 1. Start target PG14 and seed it

```bash
./scripts/manual_test/start_pg14.sh
./scripts/manual_test/seed_target.sh
```

### 2. Start metastore and seed PG14 data types

```bash
make up
make alembic-head
uv run python -m backend.scripts.seed_data_types --file backend/scripts/data/postgres14.yaml
```

### 3. Create user + system in metastore

Use Swagger at `http://localhost:8000/docs` or curl:

- `POST /api/v1/users` — create a user (or use an existing admin from seed)
- `POST /api/v1/auth/login` — get token
- `POST /api/v1/systems` with `code=demo_pg14`, `flavor_code=postgres14` (match the code from the seed YAML)

Remember the `system_code` and credentials.

### 4. Inspect-only (no metastore interaction, sanity check)

```bash
cd crawler
uv run aide-crawler inspect \
  --connection-url "postgresql+psycopg://crawler:crawler@localhost:5434/target" \
  --schemas demo \
  --format json
```

Should dump columns including arrays.

### 5. Full crawl (inspect → normalize → diff → apply → report)

```bash
cd crawler
uv run aide-crawler crawl \
  --system-code demo_pg14 \
  --connection-url "postgresql+psycopg://crawler:crawler@localhost:5434/target" \
  --metastore-url http://localhost:8000 \
  --metastore-user <user> \
  --metastore-password <pw> \
  --schemas demo \
  --format text
```

- 1st run → all tables appear as new in diff, applier creates datasets
- 2nd run on unchanged schema → empty diff
- Mutate target (e.g. `ALTER TABLE demo.products ADD COLUMN color text;`) and rerun → diff shows the change

## Cleanup

```bash
docker rm -f aide-crawler-target-pg14
make stop
```
