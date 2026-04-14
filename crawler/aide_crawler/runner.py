from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

from aide_schemas.crawl_run import CrawlRunCreate, CrawlRunUpdate, CrawlStatus
from aide_sdk import AideClient

from aide_crawler.applier import apply_new_datasets
from aide_crawler.differ import classify_and_diff
from aide_crawler.inspector import run_inspection
from aide_crawler.normalizer import normalize
from aide_crawler.type_cache import TypeCache


def format_report(*args, **kwargs):  # type: ignore[misc]
    """Thin shim — real implementation lives in reporter.py (Task 11).

    Imported lazily to avoid a broken top-level import while reporter.py
    is being rewritten.  Once Task 11 lands this shim can be replaced by
    a direct ``from aide_crawler.reporter import format_report``.
    """
    from aide_crawler.reporter import format_report as _real  # noqa: PLC0415

    return _real(*args, **kwargs)


async def run_crawl(
    *,
    system_code: str,
    connection_url: str | None,
    metastore_url: str,
    metastore_user: str,
    metastore_password: str,
    include_schemas: list[str] | None = None,
    exclude_schemas: list[str] | None = None,
    include_tables: list[str] | None = None,
    exclude_tables: list[str] | None = None,
    output_format: str = "text",
    output_file: str | None = None,
) -> None:
    if not connection_url:
        print(
            "Error: --connection-url or AIDE_CRAWLER_CONNECTION_URL is required",
            file=sys.stderr,
        )
        raise SystemExit(1)

    async with AideClient(
        base_url=metastore_url,
        username=metastore_user,
        password=metastore_password,
    ) as client:
        systems_page = await client.systems.list(params={"code": system_code})
        if not systems_page.items:
            print(
                f"Error: System '{system_code}' not found in metastore",
                file=sys.stderr,
            )
            raise SystemExit(1)
        system = systems_page.items[0]
        system_id = system.id
        flavor_id = system.flavor_id

        dt_page = await client.data_types.list(
            params={"system_flavor_id": str(flavor_id)}
        )
        if dt_page.total == 0:
            print(
                "Error: No DataTypes found for system flavor. "
                "Seed DataTypes before crawling.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        type_cache = await TypeCache.load(
            client,
            flavor_id=flavor_id,
            flavor_code=getattr(system, "flavor_code", None),
        )

        crawl_config: dict[str, Any] = {
            "include_schemas": include_schemas,
            "exclude_schemas": exclude_schemas,
            "include_tables": include_tables,
            "exclude_tables": exclude_tables,
        }
        crawl_run = await client.crawl_runs.create(
            CrawlRunCreate(
                system_id=system_id,
                status=CrawlStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
                config=crawl_config,
            )
        )

        try:
            inspection = run_inspection(
                connection_url,
                include_schemas=include_schemas,
                exclude_schemas=exclude_schemas,
                include_tables=include_tables,
                exclude_tables=exclude_tables,
            )

            normalized = normalize(inspection)

            to_apply, payload = await classify_and_diff(client, system_id, normalized)

            applied = await apply_new_datasets(
                client,
                system_id=system_id,
                datasets=to_apply,
                type_cache=type_cache,
            )
            payload.new_datasets_applied = [
                {
                    "object_name": a.object_name,
                    "dataset_id": str(a.dataset_id),
                    "fields_count": a.fields_count,
                }
                for a in applied
            ]

            if output_file:
                with open(output_file, "w") as f:
                    format_report(payload, output_format, f)
                print(f"Report written to {output_file}", file=sys.stderr)
            else:
                format_report(payload, output_format)

            await client.crawl_runs.update(
                crawl_run.id,
                CrawlRunUpdate(
                    status=CrawlStatus.COMPLETED,
                    finished_at=datetime.now(timezone.utc),
                    summary=payload.counts(),
                    diff_payload=payload.to_dict(),
                    row_version=crawl_run.row_version,
                ),
            )

        except Exception as exc:
            await client.crawl_runs.update(
                crawl_run.id,
                CrawlRunUpdate(
                    status=CrawlStatus.FAILED,
                    finished_at=datetime.now(timezone.utc),
                    error_message=str(exc),
                    row_version=crawl_run.row_version,
                ),
            )
            raise


async def run_inspect(
    *,
    connection_url: str,
    include_schemas: list[str] | None = None,
    include_tables: list[str] | None = None,
    output_format: str = "text",
) -> None:
    """Inspect-only mode: no metastore interaction."""
    inspection = run_inspection(
        connection_url,
        include_schemas=include_schemas,
        include_tables=include_tables,
    )

    if output_format == "json":
        data = {
            "dialect": inspection.dialect_name,
            "database": inspection.database_name,
            "schemas": inspection.schemas,
            "tables": [
                {
                    "schema": t.schema_name,
                    "table": t.table_name,
                    "is_view": t.is_view,
                    "columns": [
                        {
                            "name": c.name,
                            "type": str(c.type),
                            "nullable": c.nullable,
                        }
                        for c in t.columns
                    ],
                    "pk_columns": t.pk_columns,
                    "unique_constraints": t.unique_constraints,
                    "indexes": t.indexes,
                    "comment": t.comment,
                }
                for t in inspection.tables
            ],
        }
        print(json.dumps(data, indent=2, default=str))
    else:
        print(f"Dialect: {inspection.dialect_name}")
        print(f"Database: {inspection.database_name}")
        print(f"Schemas: {', '.join(inspection.schemas)}")
        print(f"Tables/Views: {len(inspection.tables)}")
        print()
        for t in inspection.tables:
            kind = "VIEW" if t.is_view else "TABLE"
            print(
                f"  {t.schema_name}.{t.table_name} ({kind}, {len(t.columns)} columns)"
            )
            for c in t.columns:
                nullable = "NULL" if c.nullable else "NOT NULL"
                print(f"    {c.name}: {c.type} {nullable}")
