# ADR-006: Deletion Strategy — Soft Delete vs Cascade Delete

**Status:** Proposed
**Date:** 2026-04-08
**Deciders:** Backend team lead, DBA

---

## 1. Context and Problem

The current AIDE data model does **not define any deletion strategy**:

- All 12 Foreign Key constraints use PostgreSQL default behavior — `RESTRICT` (no `ondelete` parameter specified in migrations).
- `BaseRepository.delete()` calls `session.delete()` — **hard delete** with no recovery.
- No `is_deleted`, `deleted_at`, or `deleted_by` fields exist in any model.
- Deleting a parent record with existing children results in a database-level `IntegrityError` (RESTRICT), which is caught only as a generic 500 error.

**Impact:**
- Superusers cannot delete entities that have children (e.g., a `System` with `Dataset` children) — the operation silently fails.
- Accidental deletion is **permanent** with no audit trail.
- No mechanism for "archiving" or "deactivating" records exists beyond the `is_active` flag on `System` and `Dataset` (which only affects business logic, not FK relationships).

### Entity Relationship Hierarchy (deletion flow)

```
SystemKind
  └─► SystemFlavor
        ├─► DataType
        │     ├─► CastRule (source)
        │     ├─► CastRule (target)
        │     └─► FieldBinding.data_type_id
        └─► System
              └─► Dataset (+ polymorphic subtables)
                    ├─► Field
                    │     └─► FieldBinding
                    └─► DatasetSchema
                          └─► FieldBinding
```

**Depth of the longest chain:** SystemKind → SystemFlavor → System → Dataset → Field → FieldBinding (6 levels).

---

## 2. Options Considered

### Option A: Soft Delete (Logical Deletion)

Add `deleted_at` / `deleted_by` columns to all entities via a new mixin. Records are never physically removed — they are "marked as deleted" and filtered out by default.

#### Data Model Changes

**New mixin** in `backend/models/mixins.py`:

| Column | Type | Description |
|--------|------|-------------|
| `deleted_at` | `DateTime`, nullable | Timestamp of logical deletion; `NULL` = active |
| `deleted_by` | `UUID`, nullable | Who performed the deletion |

**`MetaDataMixin`** becomes: `UUIDMixin + TimestampMixin + UserTrackingMixin + NoteMixin + SoftDeleteMixin`.

#### Implementation Summary

| Layer | Change |
|-------|--------|
| **Models** | Add `SoftDeleteMixin` to `MetaDataMixin`; all 11 core models gain `deleted_at`, `deleted_by` |
| **Repository** | Override `delete()` → set `deleted_at = now()`, no `session.delete()` |
| **Repository** | Add default filter `WHERE deleted_at IS NULL` to `get`, `get_multi`, `get_multi_paginated` |
| **Repository** | New methods: `restore(obj_id)`, `purge(obj_id)` (hard-delete) |
| **Service** | `delete()` sets `deleted_by` from current user, cascades soft-delete to children |
| **API** | New `POST /restore/{obj_id}` endpoint (superuser-only) |
| **Migration** | `ALTER TABLE ... ADD COLUMN deleted_at, deleted_by` for all tables |
| **Unique constraints** | Must become **partial unique indexes** (`WHERE deleted_at IS NULL`) to allow re-creation of logically deleted records |
| **FK constraints** | Remain `RESTRICT` — no physical deletion means FKs are never violated |

#### Assessment

| Dimension | Assessment |
|-----------|------------|
| Complexity | **High** — touches every query, every unique constraint, adds restore/purge logic |
| Migration risk | **Medium** — additive columns, but unique constraint conversion requires careful migration |
| Data integrity | **High** — no physical data loss, full audit trail |
| Performance | **Medium** — indexes on `deleted_at` required; table size grows over time |
| Query complexity | **High** — every SELECT must include `WHERE deleted_at IS NULL` |
| Storage | **Grows** — deleted data stays in tables; periodic purge job needed |
| Compliance / Audit | **Excellent** — who deleted what and when is always recorded |

**Pros:**
- Full undo / restore capability
- Built-in audit trail (`deleted_at`, `deleted_by`)
- No FK integrity violations — parent-child relationships preserved
- Consistent with `is_active` patterns already present on `System` and `Dataset`
- Enables "trash bin" UI for superusers

**Cons:**
- Every query must be aware of soft-delete filter (risk of data leaks if forgotten)
- Unique constraints become complex (partial indexes)
- Table growth — "deleted" rows remain until purged
- Polymorphic dataset subtables require coordinated soft-delete
- Cascading soft-delete must be implemented manually in application code (not enforced by DB)
- Testing complexity increases significantly

---

### Option B: Hard Delete with ON DELETE CASCADE

Set `ondelete="CASCADE"` on all ForeignKey constraints. When a parent is deleted, all children are automatically removed by the database engine.

#### Data Model Changes

**No new columns.** Only FK constraint changes:

| FK Constraint | Current | Proposed |
|---------------|---------|----------|
| SystemFlavor.kind_id → SystemKind | RESTRICT | CASCADE |
| System.flavor_id → SystemFlavor | RESTRICT | CASCADE |
| System.credential_ref_id → CredentialRef | RESTRICT | SET NULL |
| Dataset.system_id → System | RESTRICT | CASCADE |
| DataType.system_flavor_id → SystemFlavor | RESTRICT | CASCADE |
| Field.dataset_id → Dataset | RESTRICT | CASCADE |
| DatasetSchema.dataset_id → Dataset | RESTRICT | CASCADE |
| FieldBinding.field_id → Field | RESTRICT | CASCADE |
| FieldBinding.dataset_schema_id → DatasetSchema | RESTRICT | CASCADE |
| FieldBinding.data_type_id → DataType | RESTRICT | CASCADE |
| CastRule.source_data_type_id → DataType | RESTRICT | CASCADE |
| CastRule.target_data_type_id → DataType | RESTRICT | CASCADE |

#### Implementation Summary

| Layer | Change |
|-------|--------|
| **Models** | Add `ondelete="CASCADE"` (or `SET NULL`) to all FK `mapped_column()` definitions |
| **Migration** | `ALTER TABLE ... DROP CONSTRAINT ..., ADD CONSTRAINT ... ON DELETE CASCADE` |
| **Repository** | No changes — `session.delete()` already works |
| **Service** | Optional: add confirmation step / count affected children before delete |
| **API** | Optional: `GET /preview-delete/{obj_id}` endpoint to show cascade impact |

#### Assessment

| Dimension | Assessment |
|-----------|------------|
| Complexity | **Low** — FK attribute change + migration; no application code changes |
| Migration risk | **Low** — constraint replacement is atomic; data is not modified |
| Data integrity | **Low** — physical deletion is permanent, no undo |
| Performance | **High** — database engine handles cascades efficiently in one transaction |
| Query complexity | **None** — no additional WHERE clauses needed |
| Storage | **Optimal** — deleted data is physically removed |
| Compliance / Audit | **Poor** — no record of what was deleted or by whom |

**Pros:**
- Minimal code changes — works at database level
- No query modifications required
- Eliminates current `IntegrityError` on parent deletion
- Database guarantees referential integrity
- No table bloat
- Polymorphic subtables handled automatically by DB cascade

**Cons:**
- **Irreversible** — deleted data cannot be recovered
- No audit trail (who deleted what, when)
- Risk of accidental mass deletion (deleting `SystemKind` cascades through entire tree)
- Silent destruction of child records — user may not realize the scope
- Requires separate audit logging if compliance requires it
- `credential_ref` requires special handling (`SET NULL` instead of CASCADE)

---

### Option C: Hybrid — Soft Delete for Core Entities + CASCADE for Leaf Entities

Apply soft delete to high-value parent entities, cascade hard-delete for leaf/detail tables.

| Entity | Strategy | Rationale |
|--------|----------|-----------|
| **SystemKind** | Soft Delete | Reference data, rarely deleted |
| **SystemFlavor** | Soft Delete | Reference data |
| **System** | Soft Delete | Core business entity |
| **Dataset** (+ subtables) | Soft Delete | Core business entity, most valuable data |
| **CredentialRef** | Soft Delete | Security-sensitive |
| **DataType** | Soft Delete | Shared catalog entity |
| **Field** | CASCADE from Dataset | Leaf of Dataset, meaningless without parent |
| **DatasetSchema** | CASCADE from Dataset | Leaf of Dataset |
| **FieldBinding** | CASCADE from Field/Schema | Junction table, always derived |
| **CastRule** | CASCADE from DataType | Derived mapping |

#### Assessment

| Dimension | Assessment |
|-----------|------------|
| Complexity | **Medium** — soft-delete on 6 entities, cascade on 4 leaf tables |
| Migration risk | **Medium** — mix of column additions and FK changes |
| Data integrity | **High** for core entities, **Low** for leaves |
| Performance | **Good** — soft-delete only on frequently queried tables; leaves are cleaned by DB |
| Query complexity | **Medium** — filter needed on 6 tables, not all |
| Compliance / Audit | **Good** — audit trail for business-critical entities |

**Pros:**
- Protects valuable data (Systems, Datasets) while keeping leaf logic simple
- Reduced query filter complexity vs full soft-delete
- Cascade handles the deepest nesting automatically
- Best balance of safety and simplicity

**Cons:**
- Two deletion patterns in one codebase — requires clear documentation
- Developers must know which strategy applies to which entity
- Soft-deleted parent with cascaded children: restoring parent does not restore children

---

## 3. Trade-off Analysis

| Criteria | A: Full Soft Delete | B: Full CASCADE | C: Hybrid |
|----------|:-------------------:|:----------------:|:---------:|
| Implementation effort | High | **Low** | Medium |
| Data recovery | **Full** | None | Partial |
| Audit / Compliance | **Excellent** | Poor | Good |
| Query complexity | High | **None** | Medium |
| Risk of accidental loss | **None** | High | Low |
| Performance impact | Medium | **None** | Low |
| Codebase consistency | Consistent | **Consistent** | Mixed |
| Long-term maintenance | High | **Low** | Medium |

### Key Trade-off

The fundamental tension is between **data safety** and **simplicity**:

- If the project is a **catalog/metadata system** where losing records means losing business knowledge → **Soft Delete (A or C)** is critical.
- If the project is a **technical registry** where data can always be re-imported from source systems → **CASCADE (B)** is acceptable with proper confirmation UIs.

Given that AIDE manages **metadata about data systems** (schemas, fields, types, credentials), this data is **non-trivially reconstructable** — losing a `Dataset` with 50 fields and 3 schema versions is expensive. This favors Option A or C.

---

## 4. Recommendation

**Option C (Hybrid)** is recommended as the best balance for AIDE:

1. Core entities (`System`, `Dataset`, `SystemKind`, `SystemFlavor`, `DataType`, `CredentialRef`) get soft-delete with `deleted_at` / `deleted_by`.
2. Leaf entities (`Field`, `DatasetSchema`, `FieldBinding`, `CastRule`) get `ON DELETE CASCADE` from their parent.
3. Restoring a soft-deleted `Dataset` re-creates it as "empty" — fields/schemas can be re-imported.

This keeps the query filter overhead manageable (6 tables vs 11) while protecting the data that matters most.

---

## 5. Implementation Notes

### Timestamp column convention — naive UTC

All timestamp columns from the soft-delete mixin (`deleted_at`) and the existing `TimestampMixin` (`created_at`, `updated_at`) are declared as **`TIMESTAMP WITHOUT TIME ZONE`** in PostgreSQL. Values are stored as UTC by convention — the timezone is implicit, not enforced by the column type.

**Rules:**

- SQLAlchemy column type: `DateTime` (not `DateTime(timezone=True)`).
- The database driver (`asyncpg`) **rejects timezone-aware `datetime` values** when writing to a naive column. Passing an aware datetime raises a driver error at flush time.
- Server-side defaults (`created_at`, `updated_at`) use `func.now()` at the DB level — no Python datetime construction needed.
- When setting these columns **manually from Python code** (e.g., soft-deleting in a service, or forcing `deleted_at` in a test fixture to exercise the soft-delete branch), strip the timezone first:

  ```python
  from datetime import datetime, timezone

  obj.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
  ```

- Reading back from the DB yields a naive `datetime` — treat it as UTC at the application boundary (attach `tzinfo=timezone.utc` before formatting for API response if the DTO requires an aware value).

**Rationale for naive-UTC over `TIMESTAMPTZ`:**

- Consistency with the existing `TimestampMixin` already used across all models — switching a subset of columns to `TIMESTAMPTZ` would fragment the schema.
- Workload is single-region UTC; timezone arithmetic in PG is unnecessary overhead.
- Explicit app-level convention (always UTC) is easier to audit than implicit driver-level conversions.

**Trade-off accepted:** developers must remember to use naive datetimes when writing from Python. This quirk is canonically documented in `CLAUDE.md` under "Timestamp columns (soft-delete mixin)".
