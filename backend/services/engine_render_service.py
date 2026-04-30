import uuid
from typing import cast

from aide_schemas.engine import RenderResult, RenderWarning

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.dataset import Dataset, DatasetKafka
from backend.models.engine import Engine, EngineImpala, EngineSpark
from backend.repositories.engine import EngineRepository
from backend.services.engine_render.base import Projection, RenderableLink
from backend.services.engine_render.impala import ImpalaRenderer
from backend.services.engine_render.spark import SparkRenderer
from backend.services.envelope_resolver import EnvelopeResolver


def _qualified_name(dataset: Dataset) -> str:
    """Best-effort fully qualified dataset name for SELECT/INSERT clauses."""
    if hasattr(dataset, "schema_name") and hasattr(dataset, "table_name"):
        catalog = getattr(dataset, "catalog_name", None)
        if catalog:
            return f"{catalog}.{dataset.schema_name}.{dataset.table_name}"  # type: ignore[attr-defined]
        return f"{dataset.schema_name}.{dataset.table_name}"  # type: ignore[attr-defined]
    if hasattr(dataset, "db_name") and hasattr(dataset, "table_name"):
        return f"{dataset.db_name}.{dataset.table_name}"  # type: ignore[attr-defined]
    if hasattr(dataset, "topic"):
        return dataset.topic  # type: ignore[attr-defined]
    return dataset.object_name


class EngineRenderService:
    async def render_sql(
        self, uow: UnitOfWork, dataset_link_id: uuid.UUID
    ) -> RenderResult:
        async with uow:
            link = await uow.dataset_links.get(dataset_link_id)
            if link is None:
                raise AppException(errors.DATASET_LINK_NOT_FOUND)
            if link.engine_id is None:
                raise AppException(errors.ENGINE_NOT_ATTACHED)

            engines_repo = cast(EngineRepository, uow.engines)
            engine = await engines_repo.get(link.engine_id)
            if engine is None:
                raise AppException(errors.ENGINE_NOT_FOUND)
            if engine.role != "compute":
                raise AppException(errors.ENGINE_NOT_RENDERABLE)

            source = await uow.datasets.get(link.source_dataset_id)
            target = await uow.datasets.get(link.target_dataset_id)
            if source is None or target is None:
                raise AppException(errors.DATASET_NOT_FOUND)

            # Walk one hop upstream for a CDC engine
            cdc_engine: Engine | None = None
            kafka_format = ""
            if isinstance(source, DatasetKafka):
                kafka_format = source.format
                upstream = await uow.dataset_links.list_by_target(source.id)
                for up_link in upstream:
                    if up_link.engine_id is None or up_link.deleted_at is not None:
                        continue
                    candidate = await engines_repo.get(up_link.engine_id)
                    if candidate is not None and candidate.role == "cdc":
                        cdc_engine = candidate
                        break

            resolver = EnvelopeResolver(
                cdc_engine=cdc_engine, kafka_format=kafka_format
            )

            field_links = await uow.field_links.list_by_dataset_link(link.id)
            projections: list[Projection] = []
            warnings: list[RenderWarning] = []
            for fl in field_links:
                source_field = await uow.fields.get(fl.source_field_id)
                target_field = await uow.fields.get(fl.target_field_id)
                if source_field is None or target_field is None:
                    warnings.append(
                        RenderWarning(
                            code="FIELD_LINK_BROKEN",
                            field=None,
                            message=f"FieldLink {fl.id} references missing field",
                        )
                    )
                    continue
                target_type = (target_field.extra or {}).get(
                    "data_type_code"
                ) or "string"
                projections.append(
                    Projection(
                        source_name=source_field.name,
                        target_name=target_field.name,
                        target_type=str(target_type),
                    )
                )

            renderable = RenderableLink(
                source=_qualified_name(source),
                target=_qualified_name(target),
                projections=projections,
            )

            if isinstance(engine, EngineSpark):
                renderer = SparkRenderer(engine)
                sql = renderer.render(renderable, resolver)
                warnings.extend(renderer.last_warnings)
            elif isinstance(engine, EngineImpala):
                impala_renderer = ImpalaRenderer(engine)
                sql = impala_renderer.render(renderable, resolver)
                warnings.extend(impala_renderer.last_warnings)
            else:
                raise AppException(errors.ENGINE_NOT_RENDERABLE)

            return RenderResult(
                engine_id=engine.id,
                engine_kind=engine.kind,
                sql=sql,
                warnings=warnings,
            )
