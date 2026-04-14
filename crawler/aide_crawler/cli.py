from typing import Optional

import typer

app = typer.Typer(name="aide-crawler", help="AIDE metadata crawler")


@app.command()
def crawl(
    system_code: str = typer.Option(..., help="System code registered in metastore"),
    connection_url: Optional[str] = typer.Option(
        None,
        envvar="AIDE_CRAWLER_CONNECTION_URL",
        help="SQLAlchemy connection URL for target RDBMS",
    ),
    metastore_url: str = typer.Option(
        "http://localhost:8001",
        envvar="AIDE_METASTORE_URL",
        help="Metastore API base URL",
    ),
    metastore_user: str = typer.Option(
        ..., envvar="AIDE_METASTORE_USER", help="Metastore username"
    ),
    metastore_password: str = typer.Option(
        ..., envvar="AIDE_METASTORE_PASSWORD", help="Metastore password"
    ),
    schemas: Optional[str] = typer.Option(
        None, help="Comma-separated list of schemas to include"
    ),
    exclude_schemas: Optional[str] = typer.Option(
        None, help="Comma-separated list of schemas to exclude"
    ),
    tables: Optional[str] = typer.Option(
        None,
        help="Comma-separated list of tables to include (format: schema.table or table). If set, only these tables are crawled.",
    ),
    exclude_tables: Optional[str] = typer.Option(
        None, help="Comma-separated list of tables to exclude"
    ),
    format: str = typer.Option("text", help="Output format: text or json"),
    output: Optional[str] = typer.Option(
        None, "-o", help="Output file path (default: stdout)"
    ),
):
    """Run full crawl pipeline: inspect -> normalize -> diff -> report."""
    import asyncio

    from aide_crawler.runner import run_crawl

    schema_list = schemas.split(",") if schemas else None
    exclude_schema_list = exclude_schemas.split(",") if exclude_schemas else None
    include_table_list = tables.split(",") if tables else None
    exclude_table_list = exclude_tables.split(",") if exclude_tables else None

    asyncio.run(
        run_crawl(
            system_code=system_code,
            connection_url=connection_url,
            metastore_url=metastore_url,
            metastore_user=metastore_user,
            metastore_password=metastore_password,
            include_schemas=schema_list,
            exclude_schemas=exclude_schema_list,
            include_tables=include_table_list,
            exclude_tables=exclude_table_list,
            output_format=format,
            output_file=output,
        )
    )


@app.command()
def inspect(
    connection_url: str = typer.Option(
        ...,
        envvar="AIDE_CRAWLER_CONNECTION_URL",
        help="SQLAlchemy connection URL for target RDBMS",
    ),
    schemas: Optional[str] = typer.Option(
        None, help="Comma-separated list of schemas to include"
    ),
    tables: Optional[str] = typer.Option(
        None,
        help="Comma-separated list of tables to include (format: schema.table or table)",
    ),
    format: str = typer.Option("text", help="Output format: text or json"),
):
    """Inspect only - output raw metadata, no metastore interaction."""
    import asyncio

    from aide_crawler.runner import run_inspect

    schema_list = schemas.split(",") if schemas else None
    table_list = tables.split(",") if tables else None
    asyncio.run(
        run_inspect(
            connection_url=connection_url,
            include_schemas=schema_list,
            include_tables=table_list,
            output_format=format,
        )
    )
