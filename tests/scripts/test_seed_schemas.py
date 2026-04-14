import pytest
from pydantic import ValidationError

from backend.scripts._seed_core import SeedFile


def test_seed_file_parses_minimal_valid_doc():
    doc = {
        "kind": {"code": "rdbms", "name": "Relational Database"},
        "flavor": {
            "code": "postgres14",
            "name": "PostgreSQL",
            "vendor": "PostgreSQL Global Development Group",
            "versions": ["14", "15"],
        },
        "types": [
            {
                "code": "bigint",
                "params_schema": {},
                "render_template": "bigint",
            },
            {
                "code": "varchar",
                "params_schema": {
                    "length": {"type": "int", "required": False, "default": None}
                },
                "render_template": "varchar({length})",
            },
        ],
    }
    parsed = SeedFile.model_validate(doc)
    assert parsed.flavor.code == "postgres14"
    assert parsed.flavor.versions == ["14", "15"]
    assert len(parsed.types) == 2
    assert parsed.types[1].params_schema["length"].type == "int"


def test_seed_file_rejects_missing_flavor_code():
    doc = {
        "kind": {"code": "rdbms", "name": "Relational Database"},
        "flavor": {"name": "PostgreSQL", "versions": ["14"]},
        "types": [],
    }
    with pytest.raises(ValidationError):
        SeedFile.model_validate(doc)


def test_seed_file_rejects_duplicate_type_codes():
    doc = {
        "kind": {"code": "rdbms", "name": "Relational Database"},
        "flavor": {"code": "postgres14", "name": "PostgreSQL", "versions": ["14"]},
        "types": [
            {"code": "bigint", "params_schema": {}, "render_template": "bigint"},
            {"code": "bigint", "params_schema": {}, "render_template": "bigint"},
        ],
    }
    with pytest.raises(ValidationError):
        SeedFile.model_validate(doc)
