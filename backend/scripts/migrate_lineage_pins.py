"""Backfill script for lineage pin columns.

After Migration A: populate source_schema_id / target_schema_id on each
active DatasetLink with MAX(version_num) DatasetSchema per side; populate
fields.origin from legacy is_tech boolean.

Idempotent. Re-run after fixing unresolved cases.

Usage:
    uv run python -m backend.scripts.migrate_lineage_pins
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import AsyncSessionLocal
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema


async def _latest_schema(
    session: AsyncSession, dataset_id: uuid.UUID
) -> DatasetSchema | None:
    stmt = (
        select(DatasetSchema)
        .where(DatasetSchema.dataset_id == dataset_id)
        .order_by(DatasetSchema.version_num.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def backfill_dataset_link_pins(session: AsyncSession) -> list[tuple]:
    """Return list of (link_id, src_max, tgt_max) for unresolved links.

    Idempotent: only touches DatasetLinks where one or both pins are NULL.
    After a successful run, a second run is a no-op.
    """
    unresolved: list[tuple] = []
    unpinned_links = select(DatasetLink).where(
        DatasetLink.deleted_at.is_(None),
        or_(
            DatasetLink.source_schema_id.is_(None),
            DatasetLink.target_schema_id.is_(None),
        ),
    )
    result = await session.execute(unpinned_links)
    for link in result.scalars():
        src_max = await _latest_schema(session, link.source_dataset_id)
        tgt_max = await _latest_schema(session, link.target_dataset_id)
        if src_max is None or tgt_max is None:
            unresolved.append((link.id, src_max, tgt_max))
            continue
        link.source_schema_id = src_max.id
        link.target_schema_id = tgt_max.id
    return unresolved


async def backfill_field_origin(session: AsyncSession) -> bool:
    """Populate fields.origin from legacy is_tech column.

    Only runs meaningfully between Migration A (origin nullable) and
    Migration B (is_tech dropped). Uses raw SQL because Field.is_tech
    is no longer an ORM attribute (Task 4 dropped it from the model).

    Post-Migration-B the is_tech column has been dropped from the fields
    table — PostgreSQL raises ProgrammingError (UndefinedColumn), which
    we treat as "nothing to backfill" and roll back silently.

    Returns True if the UPDATE ran, False if we detected the post-B state
    and skipped.

    Idempotent: only updates rows where is_tech=True and origin='mapped'.
    """
    from sqlalchemy.exc import ProgrammingError

    try:
        await session.execute(
            text(
                "UPDATE fields SET origin = 'tech' "
                "WHERE is_tech = TRUE AND origin = 'mapped'"
            )
        )
        return True
    except ProgrammingError as exc:
        # Post-Migration-B state: is_tech column dropped. Anything else
        # should propagate.
        err_text = str(getattr(exc, "orig", exc))
        if "is_tech" not in err_text.lower():
            raise
        await session.rollback()
        print(
            "fields.is_tech column not found — origin backfill skipped "
            "(post-Migration-B state).",
            flush=True,
        )
        return False


async def main() -> int:
    async with AsyncSessionLocal() as session:
        unresolved = await backfill_dataset_link_pins(session)
        # Persist link writes BEFORE attempting the field backfill.
        # If the field step rolls back (post-Migration-B) it must not
        # discard the link writes performed above.
        await session.commit()

        await backfill_field_origin(session)
        await session.commit()

    if unresolved:
        print(
            "UNRESOLVED LINKS (source or target dataset has no DatasetSchema):",
            flush=True,
        )
        for row in unresolved:
            print(f"  {row}", flush=True)
        return 1
    print("Backfill complete.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
