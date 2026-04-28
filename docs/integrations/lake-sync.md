# Lake-Sync — Provisioning a lake target from a source dataset

AIDE creates the target chain (`DatasetHive` + `DatasetSchema v1` +
`Field`s + `FieldBinding`s + `TypeInstance` trees) plus a pinned
`DatasetLink` from a single backend call.

## Pre-requisites

1. The source dataset has been crawled and has at least one
   `DatasetSchema` with `FieldBinding` rows.
2. The lake `System` exists, with `flavor.code == "iceberg_v2"`. Create
   via `POST /api/v1/systems` if absent.
3. Default cast rules and Iceberg type catalog are seeded:
   ```
   uv run python -m backend.scripts.seed_data_types \
       --file backend/scripts/data/iceberg_v2.yaml
   uv run python -m backend.scripts.seed_cast_rules \
       --file backend/scripts/data/casts_pg14_to_iceberg_v2.yaml
   ```
4. If you plan to use `tech_template_id`, the backend has been
   restarted since extending `tech_type_resolver.yaml` with the
   `iceberg_v2` branch. (The resolver is loaded at module-load time.)

## Endpoint

```
POST /api/v1/datasets/{source_dataset_id}/lake-sync
```

Requires superuser auth.

### Request body

```json
{
  "target_system_id": "uuid",
  "target_layer": "core",
  "db_name": "lake",
  "table_name": "users",
  "catalog_uri": "thrift://hms:9083",
  "location": "s3://bucket/path/users",
  "partition_cols": ["dt"],
  "is_external": true,
  "overrides": {
    "amount": {"data_type_code": "string"}
  },
  "tech_template_id": "uuid",
  "tech_overrides": [
    {"name": "valid_from", "type_code": "TIMESTAMP"}
  ]
}
```

`location`, `partition_cols`, `overrides`, `tech_template_id`, and `tech_overrides` are all optional. `is_external` defaults to `true`.

### Response

```json
{
  "target_dataset_id": "uuid",
  "target_dataset_schema_id": "uuid",
  "dataset_link_id": "uuid",
  "mapped_field_count": 12,
  "tech_field_count": 4,
  "warnings": [
    {
      "field_name": "doc",
      "code": "UNSUPPORTED_TYPE_FALLBACK",
      "detail": "no CastRule for xml → iceberg_v2; used 'string'"
    }
  ]
}
```

## Override semantics

Overrides apply to the root TypeInstance only. For an `array<X>` source
column, override `data_type_code: "list"` produces `list<X-resolved>`;
the inner element type is still resolved via cast rules. Nested
overrides are not supported in this release.

## Error codes (most common)

- `DATASET_ALREADY_EXISTS` (409) — a `DatasetHive` with the requested
  `(target_system_id, db_name, table_name)` already exists.
- `LAKE_SYNC_TARGET_FLAVOR_MISMATCH` (422) — target system's flavor is
  not `iceberg_v2`.
- `LAKE_SYNC_UNKNOWN_OVERRIDE_FIELD` (422) — `overrides` references a
  field name absent from the source dataset's roots.
- `LAKE_SYNC_AMBIGUOUS_CAST` (422) — multiple cast rules match for some
  field with no override. Response carries
  `details: {"field": "<name>", "candidates": ["<code>", ...]}`;
  remediate by adding the field to `overrides`.
- `LAKE_SYNC_NO_SOURCE_SCHEMA` (422) — source has no `DatasetSchema`
  with `FieldBinding` rows.
- `DATA_TYPE_NOT_FOUND` (404) — an override's `data_type_code` does not
  exist in the target flavor.

## Re-running

Lake-sync is non-idempotent: a second call with the same target
returns 409. To recreate from scratch, in order:

1. Delete the `DatasetLink` (otherwise schema-pin RESTRICT FKs block
   the next step).
2. Delete the target `Dataset`.
3. Re-invoke `lake-sync`.

Alternatively, evolve the target via `DatasetSchema` / `FieldBinding`
APIs.

## SDK example

```python
from aide_sdk import AideClient
from aide_schemas.lake_sync import LakeSyncRequest, FieldOverride

async with AideClient(base_url, username, password) as client:
    resp = await client.lake_sync.create(
        source_dataset_id,
        LakeSyncRequest(
            target_system_id=lake_system_id,
            target_layer="core",
            db_name="lake",
            table_name="users",
            catalog_uri="thrift://hms:9083",
            overrides={"amount": FieldOverride(data_type_code="string")},
        ),
    )
    print(resp.target_dataset_id, resp.warnings)
```
