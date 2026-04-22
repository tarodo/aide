from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import AsyncSessionLocal
from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)


@dataclass
class SeedReport:
    templates_inserted: int = 0
    templates_unchanged: int = 0
    fields_inserted: int = 0
    fields_unchanged: int = 0
    details: list[str] = field(default_factory=list)


async def seed_from_file(session: AsyncSession, file: Path) -> SeedReport:
    with file.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    report = SeedReport()
    for tpl_entry in doc.get("templates", []):
        code = tpl_entry["code"]
        existing = (
            (
                await session.execute(
                    select(TechFieldTemplate).where(TechFieldTemplate.code == code)
                )
            )
            .scalars()
            .first()
        )

        if existing is None:
            tpl = TechFieldTemplate(
                code=code,
                name=tpl_entry["name"],
                layer=tpl_entry["layer"],
            )
            session.add(tpl)
            await session.flush()
            report.templates_inserted += 1
        else:
            tpl = existing
            report.templates_unchanged += 1

        existing_fields = (
            (
                await session.execute(
                    select(TechFieldTemplateField).where(
                        TechFieldTemplateField.template_id == tpl.id
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_by_name = {f.name: f for f in existing_fields}

        for field_entry in tpl_entry.get("fields", []):
            fname = field_entry["name"]
            if fname in existing_by_name:
                report.fields_unchanged += 1
                continue
            session.add(
                TechFieldTemplateField(
                    template_id=tpl.id,
                    name=fname,
                    type_code=field_entry["type_code"],
                    order=field_entry.get("order", 0),
                )
            )
            report.fields_inserted += 1
    await session.flush()
    return report


async def _run_cli(file: Path, dry_run: bool) -> SeedReport:
    async with AsyncSessionLocal() as session:
        report = await seed_from_file(session, file)
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
        return report


def _entry() -> None:
    parser = argparse.ArgumentParser(description="Seed tech-field templates.")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(_run_cli(args.file, args.dry_run))
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(
        f"{prefix}templates: +{report.templates_inserted} "
        f"={report.templates_unchanged} | "
        f"fields: +{report.fields_inserted} ={report.fields_unchanged}"
    )


if __name__ == "__main__":
    _entry()
