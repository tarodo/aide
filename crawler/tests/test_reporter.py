import io
import json

from aide_crawler.differ import DiffResult
from aide_crawler.normalizer import NormalizedDataset, NormalizedField
from aide_crawler.reporter import format_report
from aide_crawler.type_map import TypeMapping


def _make_diff() -> DiffResult:
    return DiffResult(
        new_datasets=[
            NormalizedDataset(
                object_name="public.orders",
                catalog_name="testdb",
                schema_name="public",
                table_name="orders",
                is_view=False,
                pk_columns=["id"],
                uq_constraints=[],
                comment=None,
                fields=[
                    NormalizedField(
                        name="id",
                        path="id",
                        type_mapping=TypeMapping("integer", {}),
                    ),
                    NormalizedField(
                        name="total",
                        path="total",
                        type_mapping=TypeMapping(
                            "numeric", {"precision": 10, "scale": 2}
                        ),
                    ),
                ],
                indexes=[],
                foreign_keys=[],
            )
        ],
        removed_datasets=[{"object_name": "public.legacy_orders", "id": "some-uuid"}],
        new_fields={},
        removed_fields={},
        type_changes=[],
        new_indexes={},
        removed_indexes={},
    )


def test_report_text():
    buf = io.StringIO()
    format_report(_make_diff(), "text", buf)
    output = buf.getvalue()
    assert "New datasets (1)" in output
    assert "public.orders" in output
    assert "Removed datasets (1)" in output
    assert "public.legacy_orders" in output


def test_report_json():
    buf = io.StringIO()
    format_report(_make_diff(), "json", buf)
    data = json.loads(buf.getvalue())
    assert data["summary"]["new_datasets"] == 1
    assert data["summary"]["removed_datasets"] == 1
