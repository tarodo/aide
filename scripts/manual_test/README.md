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
- `POST /api/v1/login/` — get token (OAuth2 form: `username`, `password`)
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

### 6. Seed Iceberg v2 types and PG14 → Iceberg cast rules

Required only the first time you exercise lake-sync.

```bash
docker compose exec app uv run python -m backend.scripts.seed_data_types \
    --file backend/scripts/data/iceberg_v2.yaml

docker compose exec app uv run python -m backend.scripts.seed_cast_rules \
    --file backend/scripts/data/casts_pg14_to_iceberg_v2.yaml
```

Both seeders are idempotent.

### 7. Register a lake System

Find the `iceberg_v2` flavor id and create a target system:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/login/ \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=<user>&password=<pw>" \
    | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

ICE_FLAVOR_ID=$(curl -s "http://localhost:8000/api/v1/system-flavors/?code=iceberg_v2" \
    -H "Authorization: Bearer $TOKEN" \
    | python -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")

LAKE_SYSTEM_ID=$(curl -s -X POST http://localhost:8000/api/v1/systems/ \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"code\":\"lake-prod\",\"name\":\"Lake\",\"flavor_id\":\"$ICE_FLAVOR_ID\"}" \
    | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
```

### 8. Trigger lake-sync for one source table

Find the source `dataset_id` (the seed creates `target.demo.products`):

```bash
SRC_SYSTEM_ID=$(curl -s "http://localhost:8000/api/v1/systems/?code=demo_pg14" \
    -H "Authorization: Bearer $TOKEN" \
    | python -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")

DATASET_ID=$(curl -s "http://localhost:8000/api/v1/datasets/?system_id=$SRC_SYSTEM_ID&size=100" \
    -H "Authorization: Bearer $TOKEN" \
    | python -c "import sys,json; items=json.load(sys.stdin)['items']; print([d['id'] for d in items if d['object_name']=='target.demo.products'][0])")
```

POST `/lake-sync`:

```bash
curl -s -X POST "http://localhost:8000/api/v1/datasets/$DATASET_ID/lake-sync" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
        \"target_system_id\": \"$LAKE_SYSTEM_ID\",
        \"target_layer\": \"core\",
        \"db_name\": \"lake\",
        \"table_name\": \"products\",
        \"catalog_uri\": \"thrift://hms:9083\",
        \"is_external\": true
    }" | python -m json.tool
```

Expected: `mapped_field_count: 11`, `tech_field_count: 0`, `warnings: []`. The `metadata` column (`jsonb`) maps to `string` via the `unsafe` cast rule.

Verify the target chain:

```bash
curl -s "http://localhost:8000/api/v1/datasets/?system_id=$LAKE_SYSTEM_ID" \
    -H "Authorization: Bearer $TOKEN" | python -m json.tool

curl -s "http://localhost:8000/api/v1/dataset-links/" \
    -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

Notes:

- `types_zoo` has columns (`inet`, `cidr`, `xml`, `tsvector`, …) without default cast rules; lake-sync emits `UNSUPPORTED_TYPE_FALLBACK` warnings and falls back to `string`. Useful to exercise fallback behavior.
- Re-running `/lake-sync` with the same `(db_name, table_name)` returns 409 `DATASET_ALREADY_EXISTS`. To recreate: delete the `DatasetLink` first, then the target `Dataset`, then re-invoke.
- Per-field override example: `"overrides": {"metadata": {"data_type_code": "string"}}` silences the warning by making the choice explicit.

## Cleanup

```bash
docker rm -f aide-crawler-target-pg14
make stop
```
