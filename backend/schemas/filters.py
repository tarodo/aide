"""Per-entity filter models and sortable field sets."""

from __future__ import annotations

import uuid
from datetime import datetime

from backend.api.filter_sort import BaseFilter


# ── System ───────────────────────────────────────────────────────────────
class SystemFilter(BaseFilter):
    code: str | None = None
    code__like: str | None = None
    name: str | None = None
    name__like: str | None = None
    is_active: bool | None = None
    flavor_id: uuid.UUID | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None


SYSTEM_SORTABLE = {"code", "name", "is_active", "created_at", "updated_at"}


# ── SystemKind ───────────────────────────────────────────────────────────
class SystemKindFilter(BaseFilter):
    code: str | None = None
    code__like: str | None = None
    name: str | None = None
    name__like: str | None = None


SYSTEM_KIND_SORTABLE = {"code", "name", "created_at", "updated_at"}


# ── SystemFlavor ─────────────────────────────────────────────────────────
class SystemFlavorFilter(BaseFilter):
    code: str | None = None
    code__like: str | None = None
    name: str | None = None
    name__like: str | None = None
    kind_id: uuid.UUID | None = None
    vendor: str | None = None
    vendor__like: str | None = None


SYSTEM_FLAVOR_SORTABLE = {"code", "name", "vendor", "created_at", "updated_at"}


# ── Dataset ──────────────────────────────────────────────────────────────
class DatasetFilter(BaseFilter):
    system_id: uuid.UUID | None = None
    layer: str | None = None
    layer__in: str | None = None
    kind: str | None = None
    kind__in: str | None = None
    is_active: bool | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None


DATASET_SORTABLE = {
    "object_name",
    "layer",
    "kind",
    "is_active",
    "created_at",
    "updated_at",
}


# ── Field ────────────────────────────────────────────────────────────────
class FieldFilter(BaseFilter):
    dataset_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    name: str | None = None
    name__like: str | None = None
    origin: str | None = None
    origin__in: str | None = None


FIELD_SORTABLE = {"name", "created_at", "updated_at"}


# ── DataType ─────────────────────────────────────────────────────────────
class DataTypeFilter(BaseFilter):
    code: str | None = None
    code__like: str | None = None
    system_flavor_id: uuid.UUID | None = None


DATA_TYPE_SORTABLE = {"code", "created_at", "updated_at"}


# ── CastRule ─────────────────────────────────────────────────────────────
class CastRuleFilter(BaseFilter):
    source_data_type_id: uuid.UUID | None = None
    target_data_type_id: uuid.UUID | None = None
    safety: str | None = None
    safety__in: str | None = None


CAST_RULE_SORTABLE = {"safety", "created_at", "updated_at"}


# ── CredentialRef ────────────────────────────────────────────────────────
class CredentialRefFilter(BaseFilter):
    provider: str | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None


CREDENTIAL_REF_SORTABLE = {"provider", "created_at", "updated_at"}


# ── DatasetLink ──────────────────────────────────────────────────────────
class DatasetLinkFilter(BaseFilter):
    source_dataset_id: uuid.UUID | None = None
    target_dataset_id: uuid.UUID | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None


DATASET_LINK_SORTABLE = {"created_at", "updated_at"}


# ── DatasetLinkCompat ────────────────────────────────────────────────────
class DatasetLinkCompatFilter(BaseFilter):
    """Filters for GET /dataset-links/compat bulk listing."""

    status: str | None = None
    status__in: str | None = None
    has_drift: bool | None = None
    dataset_id: uuid.UUID | None = None
    system_id: uuid.UUID | None = None


DATASET_LINK_COMPAT_SORTABLE = {"status", "updated_at"}


# ── DatasetSchema ────────────────────────────────────────────────────────
class DatasetSchemaFilter(BaseFilter):
    dataset_id: uuid.UUID | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None


DATASET_SCHEMA_SORTABLE = {"version_num", "created_at", "updated_at"}


# ── FieldBinding ─────────────────────────────────────────────────────────
class FieldBindingFilter(BaseFilter):
    field_id: uuid.UUID | None = None
    dataset_schema_id: uuid.UUID | None = None
    type_instance_id: uuid.UUID | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None


FIELD_BINDING_SORTABLE = {"position", "created_at", "updated_at"}


# ── FieldClassification ──────────────────────────────────────────────────
class FieldClassificationFilter(BaseFilter):
    field_id: uuid.UUID | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None


FIELD_CLASSIFICATION_SORTABLE = {"created_at", "updated_at"}


# ── TypeInstance ─────────────────────────────────────────────────────────
class TypeInstanceFilter(BaseFilter):
    data_type_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    slot: str | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None


TYPE_INSTANCE_SORTABLE = {"slot", "created_at", "updated_at"}


# ── User ─────────────────────────────────────────────────────────────────
class UserFilter(BaseFilter):
    email: str | None = None
    email__like: str | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None
    user_type: str | None = None
    user_type__in: str | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None


USER_SORTABLE = {
    "email",
    "full_name",
    "is_active",
    "user_type",
    "created_at",
    "updated_at",
}


# ── CrawlRun ─────────────────────────────────────────────────────────────
class CrawlRunFilter(BaseFilter):
    system_id: uuid.UUID | None = None
    status: str | None = None
    status__in: str | None = None
    started_at__gte: datetime | None = None
    started_at__lte: datetime | None = None


CRAWL_RUN_SORTABLE = {"status", "started_at", "finished_at", "created_at"}


# ── TechFieldTemplate ────────────────────────────────────────────────────
class TechFieldTemplateFilter(BaseFilter):
    code: str | None = None
    layer: str | None = None


TECH_FIELD_TEMPLATE_SORTABLE = {"code", "name", "layer", "created_at"}
