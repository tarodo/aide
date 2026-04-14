from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.uow import UnitOfWork
from backend.scripts._seed_core import SeedReport, seed_from_file


async def _main(
    file: Path,
    dry_run: bool = False,
    session_factory: Callable[[], AsyncSession] | None = None,
) -> SeedReport:
    if session_factory is not None:
        session = session_factory()
        try:
            report = await seed_from_file(session, file)
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
            return report
        finally:
            await session.close()
    else:
        uow = UnitOfWork()
        await uow.__aenter__()
        try:
            report = await seed_from_file(uow.session, file)
            if dry_run:
                await uow.rollback()
            else:
                await uow.commit()
            return report
        finally:
            await uow.session.close()


def _print_report(report: SeedReport, dry_run: bool) -> None:
    prefix = "[DRY RUN] " if dry_run else ""
    print(
        f"{prefix}kind={report.kind} flavor={report.flavor} "
        f"types: +{report.types_inserted} ~{report.types_updated} "
        f"={report.types_unchanged} restored={report.types_restored}"
    )


def _entry() -> None:
    parser = argparse.ArgumentParser(description="Seed data types from a YAML file.")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(_main(args.file, dry_run=args.dry_run))
    _print_report(report, dry_run=args.dry_run)


if __name__ == "__main__":
    _entry()
