# ETL Pre-Flight — Using AIDE's compat endpoint

AIDE is the data contract between a source and a target. Before running an
ETL load, the worker asks AIDE whether the contract is still valid. If it is
not, the load is blocked until a human re-pins the `DatasetLink` or updates
the target schema.

## Flow

1. The ETL worker knows its `dataset_link_id` — either from static config or
   resolved by name pair (`source_dataset`, `target_dataset`) via the SDK's
   `dataset_links.list(...)`.
2. Call `GET /api/v1/dataset-links/{dataset_link_id}/compat` (or
   `aide_client.dataset_links.compat(link_id)` via the SDK).
3. Switch on `response.status`:
   - `"error"` — abort the load. Alert the contract owners. The report's
     `field_compat[*].issues` lists what broke.
   - `"warn"` — log each issue. Proceed by default. A strict-mode worker
     config may escalate `warn` to abort.
   - `"ok"` — proceed.
4. If `response.pin_drift.source.has_drift` or
   `response.pin_drift.target.has_drift` is true, the contract is
   out-of-date even if not broken. Emit a notification for schema owners.
   Proceed with the load.

## Example

```python
async with AideClient(base_url, username, password) as client:
    report = await client.dataset_links.compat(dataset_link_id)
    if report.status.value == "error":
        raise LoadAbort(
            f"DatasetLink {dataset_link_id}: "
            + ", ".join(sorted({i.value for fc in report.field_compat for i in fc.issues}))
        )
    if report.status.value == "warn" and worker_config.strict:
        raise LoadAbort("strict mode: contract has warnings")
    # proceed
```

## Semantics

- `status == "error"`: at least one `field_compat` entry has severity
  `error` — type incompatible, no cast rule, or a side is unbound in its
  pinned schema.
- `status == "warn"`: no errors, but something is imperfect — a cast is
  required, a column tightens from nullable → NOT NULL, or the pin has
  drifted from the latest available schema.
- `status == "ok"`: exact type match, no drift, no warnings.

## When pin drift is detected

Pin drift means the source or target dataset has a newer `DatasetSchema`
than the link's pin. Drift alone does not break the contract — existing
field types are still consistent against the pinned schemas. But it means
someone bumped the schema without updating the link, which is usually a
signal that the contract needs re-pinning.

## Webhooks and push alerts

Not yet supported. Poll `GET /api/v1/dataset-links/compat?status=error`
on a schedule for dashboard/alert scenarios.
