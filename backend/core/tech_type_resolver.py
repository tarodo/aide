from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml


@dataclass(frozen=True)
class TechTypeResolver:
    """Maps abstract (flavor, type_code) pairs to concrete data-type codes."""

    _table: Mapping[tuple[str, str], str]

    @classmethod
    def from_yaml(cls, path: Path) -> "TechTypeResolver":
        with path.open("r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        mappings = doc.get("mappings", [])
        table: dict[tuple[str, str], str] = {}
        for entry in mappings:
            key = (entry["flavor"], entry["type_code"])
            if key in table:
                raise ValueError(
                    f"Duplicate mapping for flavor={key[0]!r}, type_code={key[1]!r}"
                )
            table[key] = entry["data_type_code"]
        return cls(_table=MappingProxyType(table))

    def resolve(self, flavor: str, type_code: str) -> str | None:
        return self._table.get((flavor, type_code))
