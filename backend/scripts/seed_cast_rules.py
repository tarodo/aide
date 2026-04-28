from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import AsyncSessionLocal
from backend.scripts._seed_cast_rules_core import (
    CastRulesSeedReport,
    seed_from_file,
)


async def _main(
    session: AsyncSession, file: Path, dry_run: bool = False
) -> CastRulesSeedReport:
    report = await seed_from_file(session, file)
    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    return report


async def _run_cli(file: Path, dry_run: bool) -> CastRulesSeedReport:
    async with AsyncSessionLocal() as session:
        return await _main(session, file, dry_run=dry_run)


def _print_report(report: CastRulesSeedReport, dry_run: bool) -> None:
    prefix = "[DRY RUN] " if dry_run else ""
    print(
        f"{prefix}cast rules: +{report.inserted} ~{report.updated} "
        f"={report.unchanged}"
    )


def _entry() -> None:
    parser = argparse.ArgumentParser(description="Seed cast rules from a YAML file.")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(_run_cli(args.file, args.dry_run))
    _print_report(report, dry_run=args.dry_run)


if __name__ == "__main__":
    _entry()
