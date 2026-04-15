import io
from io import StringIO

from aide_crawler.differ import DiffPayload
from aide_crawler.reporter import format_report, report_json, report_text


def test_report_text_applied_datasets():
    payload = DiffPayload(
        new_datasets_applied=[
            {"object_name": "public.users", "dataset_id": "abc", "fields_count": 3}
        ],
    )
    buf = StringIO()
    report_text(payload, buf)
    out = buf.getvalue()
    assert "public.users" in out
    assert "3" in out


def test_report_text_existing_diff_lines():
    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "public.orders",
                "dataset_id": "xyz",
                "new_fields": [
                    {"name": "shipped_at", "code": "timestamp", "params": {}}
                ],
                "removed_fields": [{"name": "legacy_col", "field_id": "f1"}],
                "type_changes": [],
            }
        ]
    )
    buf = StringIO()
    report_text(payload, buf)
    out = buf.getvalue()
    assert "public.orders" in out
    assert "shipped_at" in out
    assert "legacy_col" in out


def test_report_text_removed_datasets():
    payload = DiffPayload(
        removed_datasets=[{"object_name": "public.gone", "dataset_id": "g1"}]
    )
    buf = StringIO()
    report_text(payload, buf)
    assert "public.gone" in buf.getvalue()


def test_report_text_summary_counts():
    payload = DiffPayload(
        new_datasets_applied=[
            {"object_name": "a", "dataset_id": "1", "fields_count": 5}
        ],
        existing_datasets_diff=[
            {
                "object_name": "b",
                "dataset_id": "2",
                "new_fields": [{"name": "x", "code": "integer", "params": {}}],
                "removed_fields": [],
                "type_changes": [],
            }
        ],
    )
    buf = StringIO()
    report_text(payload, buf)
    out = buf.getvalue()
    assert "new_datasets_applied" in out or "Applied" in out
    assert "1" in out


def test_report_json_schema_version():
    payload = DiffPayload()
    buf = StringIO()
    report_json(payload, buf)
    assert '"schema_version": 1' in buf.getvalue()


def test_report_renders_type_changes_in_text():
    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "target.demo.products",
                "dataset_id": "00000000-0000-0000-0000-000000000001",
                "new_fields": [],
                "removed_fields": [],
                "type_changes": [
                    {
                        "field_name": "name",
                        "field_id": "00000000-0000-0000-0000-000000000002",
                        "before": {"code": "varchar", "params": {"length": 255}},
                        "after": {"code": "text", "params": {}},
                        "full_before": {},
                        "full_after": {},
                    }
                ],
            }
        ],
    )
    buf = io.StringIO()
    report_text(payload, buf)
    text = buf.getvalue()
    assert "~ name: varchar(length=255) -> text" in text


def test_report_renders_composite_type_change():
    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "target.demo.products",
                "dataset_id": "00000000-0000-0000-0000-000000000001",
                "new_fields": [],
                "removed_fields": [],
                "type_changes": [
                    {
                        "field_name": "nums",
                        "field_id": "00000000-0000-0000-0000-000000000002",
                        "before": {"code": "array", "params": {}},
                        "after": {"code": "array", "params": {}},
                        "full_before": {
                            "code": "array",
                            "params": {},
                            "children": [
                                {
                                    "slot": "item",
                                    "node": {
                                        "code": "integer",
                                        "params": {},
                                        "children": [],
                                    },
                                }
                            ],
                        },
                        "full_after": {
                            "code": "array",
                            "params": {},
                            "children": [
                                {
                                    "slot": "item",
                                    "node": {
                                        "code": "bigint",
                                        "params": {},
                                        "children": [],
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    )
    buf = io.StringIO()
    report_text(payload, out=buf)
    text = buf.getvalue()
    assert "~ nums: array<item: integer> -> array<item: bigint>" in text


def test_format_report_dispatches_by_fmt():
    payload = DiffPayload()
    json_buf = StringIO()
    format_report(payload, "json", json_buf)
    assert '"schema_version"' in json_buf.getvalue()

    text_buf = StringIO()
    format_report(payload, "text", text_buf)
    assert text_buf.getvalue()  # non-empty
