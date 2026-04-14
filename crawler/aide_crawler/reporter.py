from __future__ import annotations

import json
import sys
from typing import IO

from aide_crawler.differ import DiffResult


def report_text(diff: DiffResult, out: IO[str] = sys.stdout) -> None:
    """Human-readable diff report."""
    out.write("=== AIDE Crawler Diff Report ===\n\n")

    if diff.new_datasets:
        out.write(f"--- New datasets ({len(diff.new_datasets)}) ---\n")
        for ds in diff.new_datasets:
            out.write(f"  + {ds.object_name}")
            if ds.is_view:
                out.write(" (view)")
            out.write(f"  [{len(ds.fields)} columns]\n")
        out.write("\n")

    if diff.removed_datasets:
        out.write(f"--- Removed datasets ({len(diff.removed_datasets)}) ---\n")
        for ds in diff.removed_datasets:
            out.write(f"  - {ds['object_name']}\n")
        out.write("\n")

    if diff.new_fields:
        total = sum(len(v) for v in diff.new_fields.values())
        out.write(f"--- New fields ({total}) ---\n")
        for obj_name, fields in diff.new_fields.items():
            for f in fields:
                type_str = (
                    f.type_mapping.data_type_code if f.type_mapping else "unknown"
                )
                out.write(f"  + {obj_name}.{f.name} ({type_str})\n")
        out.write("\n")

    if diff.removed_fields:
        total = sum(len(v) for v in diff.removed_fields.values())
        out.write(f"--- Removed fields ({total}) ---\n")
        for obj_name, fields in diff.removed_fields.items():
            for f in fields:
                out.write(f"  - {obj_name}.{f['name']}\n")
        out.write("\n")

    if diff.type_changes:
        out.write(f"--- Type changes ({len(diff.type_changes)}) ---\n")
        for tc in diff.type_changes:
            out.write(
                f"  ~ {tc.dataset_object_name}.{tc.field_name}: "
                f"{tc.old_type} -> {tc.new_type}\n"
            )
        out.write("\n")

    out.write("--- Summary ---\n")
    out.write(f"  New datasets:     {len(diff.new_datasets)}\n")
    out.write(f"  Removed datasets: {len(diff.removed_datasets)}\n")
    out.write(f"  New fields:       {sum(len(v) for v in diff.new_fields.values())}\n")
    out.write(
        f"  Removed fields:   {sum(len(v) for v in diff.removed_fields.values())}\n"
    )
    out.write(f"  Type changes:     {len(diff.type_changes)}\n")


def report_json(diff: DiffResult, out: IO[str] = sys.stdout) -> None:
    """Machine-readable JSON diff report."""
    data = {
        "new_datasets": [
            {
                "object_name": ds.object_name,
                "is_view": ds.is_view,
                "fields_count": len(ds.fields),
            }
            for ds in diff.new_datasets
        ],
        "removed_datasets": [
            {"object_name": ds["object_name"], "id": ds.get("id")}
            for ds in diff.removed_datasets
        ],
        "new_fields": {
            obj: [
                {
                    "name": f.name,
                    "type": f.type_mapping.data_type_code if f.type_mapping else None,
                }
                for f in fields
            ]
            for obj, fields in diff.new_fields.items()
        },
        "removed_fields": {
            obj: [{"name": f["name"]} for f in fields]
            for obj, fields in diff.removed_fields.items()
        },
        "type_changes": [
            {
                "dataset": tc.dataset_object_name,
                "field": tc.field_name,
                "old_type": tc.old_type,
                "new_type": tc.new_type,
            }
            for tc in diff.type_changes
        ],
        "summary": {
            "new_datasets": len(diff.new_datasets),
            "removed_datasets": len(diff.removed_datasets),
            "new_fields": sum(len(v) for v in diff.new_fields.values()),
            "removed_fields": sum(len(v) for v in diff.removed_fields.values()),
            "type_changes": len(diff.type_changes),
        },
    }
    json.dump(data, out, indent=2, default=str)
    out.write("\n")


def format_report(diff: DiffResult, fmt: str, out: IO[str] = sys.stdout) -> None:
    if fmt == "json":
        report_json(diff, out)
    else:
        report_text(diff, out)
