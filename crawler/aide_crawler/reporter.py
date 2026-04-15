from __future__ import annotations

import json
import sys
from typing import IO

from aide_crawler.differ import DiffPayload


def _fmt_type(t: dict) -> str:
    params = t.get("params") or {}
    if not params:
        return t["code"]
    kv = ", ".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{t['code']}({kv})"


def report_text(payload: DiffPayload, out: IO[str] = sys.stdout) -> None:
    out.write("=== AIDE Crawler Report ===\n\n")

    if payload.new_datasets_applied:
        out.write(f"--- Applied ({len(payload.new_datasets_applied)}) ---\n")
        for d in payload.new_datasets_applied:
            out.write(f"  Applied: {d['object_name']}  [{d['fields_count']} fields]\n")
        out.write("\n")

    if payload.existing_datasets_diff:
        out.write(
            f"--- Existing datasets with changes "
            f"({len(payload.existing_datasets_diff)}) ---\n"
        )
        for entry in payload.existing_datasets_diff:
            out.write(f"  * {entry['object_name']}\n")
            for nf in entry["new_fields"]:
                out.write(f"      + {nf['name']} ({nf['code']})\n")
            for rf in entry["removed_fields"]:
                out.write(f"      - {rf['name']}\n")
            for change in entry.get("type_changes", []):
                before_str = _fmt_type(change["before"])
                after_str = _fmt_type(change["after"])
                out.write(f"      ~ {change['field_name']}: {before_str} -> {after_str}\n")
        out.write("\n")

    if payload.removed_datasets:
        out.write(f"--- Removed datasets ({len(payload.removed_datasets)}) ---\n")
        for d in payload.removed_datasets:
            out.write(f"  - {d['object_name']}\n")
        out.write("\n")

    out.write("--- Summary ---\n")
    for k, v in payload.counts().items():
        out.write(f"  {k}: {v}\n")


def report_json(payload: DiffPayload, out: IO[str] = sys.stdout) -> None:
    json.dump(payload.to_dict(), out, indent=2, default=str)
    out.write("\n")


def format_report(payload: DiffPayload, fmt: str, out: IO[str] = sys.stdout) -> None:
    if fmt == "json":
        report_json(payload, out)
    else:
        report_text(payload, out)
