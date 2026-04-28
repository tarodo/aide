import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.filter_sort import FilterOp, FilterSpec
from backend.models import SystemKind
from backend.repositories.system_kind import SystemKindRepository


async def _seed(session: AsyncSession) -> None:
    rows = [
        SystemKind(code="FLT_A", name="Apple"),
        SystemKind(code="FLT_B", name="Banana"),
        SystemKind(code="FLT_C", name="Cherry 50%"),
        SystemKind(code="FLT_D", name="Date"),
    ]
    session.add_all(rows)
    await session.flush()


@pytest.mark.asyncio
async def test_filter_eq(transactional_session: AsyncSession):
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    items, total = await repo.get_multi_paginated(
        filters={"code": FilterSpec(field="code", op=FilterOp.EQ, value="FLT_A")}
    )
    assert total == 1 and items[0].code == "FLT_A"


@pytest.mark.asyncio
async def test_filter_in(transactional_session: AsyncSession):
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    items, total = await repo.get_multi_paginated(
        filters={
            "code": FilterSpec(field="code", op=FilterOp.IN, value=["FLT_A", "FLT_C"])
        }
    )
    codes = sorted(i.code for i in items)
    assert total == 2 and codes == ["FLT_A", "FLT_C"]


@pytest.mark.asyncio
async def test_filter_gt_gte_lt_lte(transactional_session: AsyncSession):
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    # GT
    _, total_gt = await repo.get_multi_paginated(
        filters={"code": FilterSpec(field="code", op=FilterOp.GT, value="FLT_B")}
    )
    assert total_gt == 2  # FLT_C, FLT_D
    # GTE
    _, total_gte = await repo.get_multi_paginated(
        filters={"code": FilterSpec(field="code", op=FilterOp.GTE, value="FLT_B")}
    )
    assert total_gte == 3
    # LT
    _, total_lt = await repo.get_multi_paginated(
        filters={"code": FilterSpec(field="code", op=FilterOp.LT, value="FLT_C")}
    )
    assert total_lt == 2  # FLT_A, FLT_B
    # LTE
    _, total_lte = await repo.get_multi_paginated(
        filters={"code": FilterSpec(field="code", op=FilterOp.LTE, value="FLT_C")}
    )
    assert total_lte == 3


@pytest.mark.asyncio
async def test_filter_like_escapes_wildcards(transactional_session: AsyncSession):
    """Raw `%` and `_` in user input must NOT act as SQL wildcards."""
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    # Only 'Cherry 50%' contains a literal '%'. A naive ILIKE without
    # escaping would match every row.
    _, total = await repo.get_multi_paginated(
        filters={"name": FilterSpec(field="name", op=FilterOp.LIKE, value="50%")}
    )
    assert total == 1


@pytest.mark.asyncio
async def test_filter_like_underscore_literal(transactional_session: AsyncSession):
    """Underscore in user input is escaped — must not act as single-char wildcard."""
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    # No row contains a literal underscore in `name`.
    _, total = await repo.get_multi_paginated(
        filters={"name": FilterSpec(field="name", op=FilterOp.LIKE, value="_")}
    )
    assert total == 0


@pytest.mark.asyncio
async def test_filter_unknown_column_raises(transactional_session: AsyncSession):
    repo = SystemKindRepository(transactional_session)
    with pytest.raises(ValueError, match="no column 'nope'"):
        await repo.get_multi_paginated(
            filters={
                "nope": FilterSpec(field="nope", op=FilterOp.EQ, value="x"),
            }
        )


@pytest.mark.asyncio
async def test_filter_plain_dict_unknown_column_raises(
    transactional_session: AsyncSession,
):
    repo = SystemKindRepository(transactional_session)
    with pytest.raises(ValueError, match="no column 'missing'"):
        await repo.get_multi_paginated(filters={"missing": "x"})


@pytest.mark.asyncio
async def test_sort_unknown_column_raises(transactional_session: AsyncSession):
    repo = SystemKindRepository(transactional_session)
    with pytest.raises(ValueError, match="no column 'nope'"):
        await repo.get_multi_paginated(sort=[("nope", False)])


@pytest.mark.asyncio
async def test_sort_desc_orders_correctly(transactional_session: AsyncSession):
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    items, _ = await repo.get_multi_paginated(
        filters={
            "code": FilterSpec(
                field="code", op=FilterOp.IN, value=["FLT_A", "FLT_B", "FLT_C"]
            )
        },
        sort=[("code", True)],
    )
    assert [i.code for i in items] == ["FLT_C", "FLT_B", "FLT_A"]
