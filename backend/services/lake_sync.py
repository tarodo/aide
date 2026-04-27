from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.cast_rule import CastRule
from backend.models.data_type import DataType
from backend.models.dataset import Dataset, DatasetHive
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.models.field import Field
from backend.models.field_binding import FieldBinding
from backend.models.field_link import FieldLink
from backend.models.system import System
from backend.models.system_flavor import SystemFlavor
from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)
from backend.models.type_instance import TypeInstance
from backend.schemas.lake_sync import (
    LakeSyncRequest,
    LakeSyncResponse,
    LakeSyncWarning,
)
from backend.services.dataset import tech_type_resolver
from backend.services.lake_sync_resolver import (
    DataTypeRef,
    SourceTI,
    TargetTI,
    resolve_target_ti,
)
from backend.services.type_instance_tree import PlanNode, create_tree


class LakeSyncService:
    async def create_lake_target(
        self,
        uow: UnitOfWork,
        source_dataset_id: uuid.UUID,
        request: LakeSyncRequest,
        applier_id: uuid.UUID | None,
    ) -> LakeSyncResponse:
        async with uow:
            return await self._impl(uow, source_dataset_id, request, applier_id)

    async def _impl(
        self,
        uow: UnitOfWork,
        source_dataset_id: uuid.UUID,
        request: LakeSyncRequest,
        applier_id: uuid.UUID | None,
    ) -> LakeSyncResponse:
        session = uow.session

        # 1. Validate source dataset.
        source_dataset = await session.get(Dataset, source_dataset_id)
        if source_dataset is None or source_dataset.deleted_at is not None:
            raise AppException(errors.DATASET_NOT_FOUND)

        # Latest non-orphan schema (highest version_num with at least one binding).
        source_schema = await self._latest_non_orphan_schema(session, source_dataset_id)
        if source_schema is None:
            raise AppException(errors.LAKE_SYNC_NO_SOURCE_SCHEMA)

        # 2. Validate target system + flavor.
        target_system = await session.get(System, request.target_system_id)
        if target_system is None:
            raise AppException(errors.SYSTEM_NOT_FOUND)
        target_flavor = await session.get(SystemFlavor, target_system.flavor_id)
        if target_flavor is None:
            raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)
        if target_flavor.code != "iceberg_v2":
            raise AppException(errors.LAKE_SYNC_TARGET_FLAVOR_MISMATCH)

        # 3. No existing target DatasetHive with same db_name/table_name.
        existing = (
            (
                await session.execute(
                    select(DatasetHive).where(
                        DatasetHive.system_id == request.target_system_id,
                        DatasetHive.db_name == request.db_name,
                        DatasetHive.table_name == request.table_name,
                        DatasetHive.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            raise AppException(errors.DATASET_ALREADY_EXISTS)

        # 4. Validate tech template if requested.
        tech_template: TechFieldTemplate | None = None
        if request.tech_template_id is not None:
            tech_template = await session.get(
                TechFieldTemplate, request.tech_template_id
            )
            if tech_template is None:
                raise AppException(errors.TECH_FIELD_TEMPLATE_NOT_FOUND)
            if tech_template.layer != request.target_layer:
                raise AppException(errors.TECH_FIELD_TEMPLATE_LAYER_MISMATCH)

        # 5. Load source root fields + bindings + TypeInstance trees.
        source_fields = await self._load_root_fields(session, source_dataset_id)
        source_bindings = await self._load_bindings(
            session, source_schema.id, [f.id for f in source_fields]
        )

        # Filter out source fields with no binding in the pinned source schema.
        # Such root fields may exist (e.g. created in newer drafts) but cannot
        # be lake-synced without a binding to read their type from.
        source_fields = [f for f in source_fields if f.id in source_bindings]

        # 6. Validate overrides reference real source field names.
        overrides = request.overrides or {}
        valid_names = {f.name for f in source_fields}
        unknown = set(overrides) - valid_names
        if unknown:
            raise AppException(errors.LAKE_SYNC_UNKNOWN_OVERRIDE_FIELD)

        # 7. Preload Iceberg DataTypes (target_lookup_by_code).
        iceberg_types = await self._load_target_data_types(session, target_flavor.id)

        # 8. Preload CastRules for all source data_type ids in trees.
        source_dt_ids = self._collect_source_data_type_ids(source_bindings)
        rules_by_source_id = await self._load_rules_for_sources(
            session, source_dt_ids, target_flavor.id
        )

        # 9. Resolve target TypeInstance plans per source root field.
        warnings: list[LakeSyncWarning] = []
        per_field_plan: list[tuple[Field, FieldBinding, TargetTI]] = []
        for fld in source_fields:
            binding = source_bindings[fld.id]
            src_ti = self._build_source_ti_tree(binding.type_instance)
            override = overrides.get(fld.name)
            target_plan = resolve_target_ti(
                src_ti,
                target_lookup_by_code=iceberg_types,
                rules_by_source_id=rules_by_source_id,
                field_override=override,
                field_name=fld.name,
                warnings=warnings,
            )
            per_field_plan.append((fld, binding, target_plan))

        # 10. Create target DatasetHive.
        target_dataset = DatasetHive(
            kind="hive",
            system_id=request.target_system_id,
            object_name=f"{request.db_name}.{request.table_name}",
            layer=request.target_layer,
            db_name=request.db_name,
            table_name=request.table_name,
            catalog_uri=request.catalog_uri,
            is_external=request.is_external,
            file_format="iceberg",
            location=request.location,
            partition_cols=request.partition_cols,
        )
        if applier_id:
            target_dataset.created_by = applier_id
            target_dataset.updated_by = applier_id
        session.add(target_dataset)
        await session.flush()

        # 11. Create target DatasetSchema v1.
        target_schema = DatasetSchema(dataset_id=target_dataset.id, version_num=1)
        if applier_id:
            target_schema.created_by = applier_id
            target_schema.updated_by = applier_id
        session.add(target_schema)
        await session.flush()

        # 12. Create mapped Fields + TypeInstance trees + FieldBindings.
        mapped_target_fields: list[tuple[Field, Field]] = []  # (source, target)
        mapped_count = 0
        for src_fld, src_binding, target_plan in per_field_plan:
            tgt_field = Field(
                dataset_id=target_dataset.id,
                name=src_fld.name,
                origin="mapped",
            )
            if applier_id:
                tgt_field.created_by = applier_id
                tgt_field.updated_by = applier_id
            session.add(tgt_field)
            await session.flush()

            ti_root_id = await create_tree(session, _target_to_plan(target_plan))

            tgt_binding = FieldBinding(
                field_id=tgt_field.id,
                dataset_schema_id=target_schema.id,
                position=src_binding.position,
                is_nullable=src_binding.is_nullable,
                type_instance_id=ti_root_id,
            )
            if applier_id:
                tgt_binding.created_by = applier_id
                tgt_binding.updated_by = applier_id
            session.add(tgt_binding)
            await session.flush()

            mapped_target_fields.append((src_fld, tgt_field))
            mapped_count += 1

        # 13. Tech fields (if requested).
        tech_count = 0
        if tech_template is not None:
            tpl_fields = (
                (
                    await session.execute(
                        select(TechFieldTemplateField).where(
                            TechFieldTemplateField.template_id == tech_template.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            tpl_fields = sorted(tpl_fields, key=lambda x: x.order)
            override_map = {o.name: o for o in (request.tech_overrides or [])}

            for tf in tpl_fields:
                ovr = override_map.get(tf.name)
                effective_code = (
                    ovr.type_code if ovr and ovr.type_code else tf.type_code
                )
                resolved_dt_code = tech_type_resolver.resolve(
                    "iceberg_v2", effective_code
                )
                if resolved_dt_code is None:
                    raise AppException(errors.TECH_TYPE_CODE_NOT_RESOLVABLE)

                target_dt = iceberg_types.get(resolved_dt_code)
                if target_dt is None:
                    raise AppException(errors.TECH_TYPE_CODE_NOT_RESOLVABLE)

                tech_field = Field(
                    dataset_id=target_dataset.id,
                    name=tf.name,
                    origin="tech",
                )
                if applier_id:
                    tech_field.created_by = applier_id
                    tech_field.updated_by = applier_id
                session.add(tech_field)
                await session.flush()

                ti = TypeInstance(
                    data_type_id=target_dt.id, type_params=None, slot=None
                )
                session.add(ti)
                await session.flush()

                tech_binding = FieldBinding(
                    field_id=tech_field.id,
                    dataset_schema_id=target_schema.id,
                    position=mapped_count + tf.order,
                    is_nullable=True,
                    type_instance_id=ti.id,
                )
                if applier_id:
                    tech_binding.created_by = applier_id
                    tech_binding.updated_by = applier_id
                session.add(tech_binding)
                await session.flush()
                tech_count += 1

        # 14. Create DatasetLink (pinned).
        link = DatasetLink(
            source_dataset_id=source_dataset_id,
            target_dataset_id=target_dataset.id,
            source_schema_id=source_schema.id,
            target_schema_id=target_schema.id,
        )
        if applier_id:
            link.created_by = applier_id
            link.updated_by = applier_id
        session.add(link)
        await session.flush()

        # 15. Create FieldLink rows for mapped fields.
        for src_fld, tgt_field in mapped_target_fields:
            fl = FieldLink(
                dataset_link_id=link.id,
                source_field_id=src_fld.id,
                target_field_id=tgt_field.id,
            )
            if applier_id:
                fl.created_by = applier_id
                fl.updated_by = applier_id
            session.add(fl)
        await session.flush()

        return LakeSyncResponse(
            target_dataset_id=target_dataset.id,
            target_dataset_schema_id=target_schema.id,
            dataset_link_id=link.id,
            mapped_field_count=mapped_count,
            tech_field_count=tech_count,
            warnings=warnings,
        )

    # ------------------------ helpers ------------------------

    async def _latest_non_orphan_schema(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> DatasetSchema | None:
        stmt = (
            select(DatasetSchema)
            .where(DatasetSchema.dataset_id == dataset_id)
            .order_by(DatasetSchema.version_num.desc())
        )
        for schema in (await session.execute(stmt)).scalars():
            has_bindings = (
                await session.execute(
                    select(FieldBinding.id)
                    .where(FieldBinding.dataset_schema_id == schema.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if has_bindings is not None:
                return schema
        return None

    async def _load_root_fields(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> list[Field]:
        stmt = (
            select(Field)
            .where(
                Field.dataset_id == dataset_id,
                Field.parent_id.is_(None),
            )
            .order_by(Field.name)
        )
        return list((await session.execute(stmt)).scalars())

    async def _load_bindings(
        self,
        session: AsyncSession,
        schema_id: uuid.UUID,
        field_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, FieldBinding]:
        if not field_ids:
            return {}
        # Eagerly load the TypeInstance subtree to a fixed depth.
        # MVP supports depth ≤ 2 (e.g. array<int>); deeper trees would
        # raise MissingGreenlet on lazy traversal — extend this chain.
        stmt = (
            select(FieldBinding)
            .where(
                FieldBinding.dataset_schema_id == schema_id,
                FieldBinding.field_id.in_(field_ids),
            )
            .options(
                selectinload(FieldBinding.type_instance).selectinload(
                    TypeInstance.data_type
                ),
                selectinload(FieldBinding.type_instance)
                .selectinload(TypeInstance.children)
                .selectinload(TypeInstance.data_type),
                selectinload(FieldBinding.type_instance)
                .selectinload(TypeInstance.children)
                .selectinload(TypeInstance.children)
                .selectinload(TypeInstance.data_type),
            )
        )
        rows = (await session.execute(stmt)).scalars().all()
        return {b.field_id: b for b in rows}

    async def _load_target_data_types(
        self, session: AsyncSession, flavor_id: uuid.UUID
    ) -> dict[str, DataTypeRef]:
        stmt = select(DataType).where(
            DataType.system_flavor_id == flavor_id,
            DataType.deleted_at.is_(None),
        )
        out: dict[str, DataTypeRef] = {}
        for dt in (await session.execute(stmt)).scalars():
            out[dt.code] = DataTypeRef(
                id=dt.id, code=dt.code, params_schema=dict(dt.params_schema)
            )
        return out

    def _collect_source_data_type_ids(
        self, bindings: dict[uuid.UUID, FieldBinding]
    ) -> set[uuid.UUID]:
        out: set[uuid.UUID] = set()
        for b in bindings.values():
            self._walk_ti_collect(b.type_instance, out)
        return out

    def _walk_ti_collect(self, ti: TypeInstance, out: set[uuid.UUID]) -> None:
        out.add(ti.data_type_id)
        for c in ti.children:
            self._walk_ti_collect(c, out)

    async def _load_rules_for_sources(
        self,
        session: AsyncSession,
        source_dt_ids: set[uuid.UUID],
        target_flavor_id: uuid.UUID,
    ) -> dict[uuid.UUID, list[tuple[DataTypeRef, dict[str, Any]]]]:
        if not source_dt_ids:
            return {}
        stmt = (
            select(CastRule)
            .where(CastRule.source_data_type_id.in_(source_dt_ids))
            .options(selectinload(CastRule.target_data_type))
        )
        rules: dict[uuid.UUID, list[tuple[DataTypeRef, dict[str, Any]]]] = {}
        for rule in (await session.execute(stmt)).scalars():
            tgt = rule.target_data_type
            if tgt.system_flavor_id != target_flavor_id:
                continue
            rules.setdefault(rule.source_data_type_id, []).append(
                (
                    DataTypeRef(
                        id=tgt.id,
                        code=tgt.code,
                        params_schema=dict(tgt.params_schema),
                    ),
                    {
                        "params": dict(rule.param_mapping or {}),
                        "safety": rule.safety,
                    },
                )
            )
        return rules

    def _build_source_ti_tree(self, ti: TypeInstance) -> SourceTI:
        node = SourceTI(
            data_type=DataTypeRef(
                id=ti.data_type.id,
                code=ti.data_type.code,
                params_schema=dict(ti.data_type.params_schema),
            ),
            type_params=dict(ti.type_params or {}),
            children=[],
        )
        for child in ti.children:
            node.children.append((child.slot or "", self._build_source_ti_tree(child)))
        return node


def _target_to_plan(target: TargetTI) -> PlanNode:
    return PlanNode(
        data_type_id=target.data_type_id,
        type_params=target.type_params,
        slot=None,
        children=[
            _target_to_plan_with_slot(slot, child) for slot, child in target.children
        ],
    )


def _target_to_plan_with_slot(slot: str, target: TargetTI) -> PlanNode:
    return PlanNode(
        data_type_id=target.data_type_id,
        type_params=target.type_params,
        slot=slot,
        children=[_target_to_plan_with_slot(s, c) for s, c in target.children],
    )
