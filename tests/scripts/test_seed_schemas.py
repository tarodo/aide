import textwrap

import pytest
from pydantic import ValidationError

from backend.scripts._seed_core import SeedFile, SeedParamSpec, load_seed_file


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


def test_load_seed_file_parses_yaml(tmp_path):
    yaml_text = textwrap.dedent("""
        kind:
          code: rdbms
          name: Relational Database
        flavor:
          code: postgres14
          name: PostgreSQL
          vendor: PostgreSQL Global Development Group
          versions: ["14"]
        types:
          - code: bigint
            params_schema: {}
            render_template: bigint
        """)
    p = tmp_path / "seed.yaml"
    p.write_text(yaml_text)

    parsed = load_seed_file(p)
    assert parsed.flavor.code == "postgres14"
    assert parsed.types[0].code == "bigint"


def test_load_seed_file_raises_on_unknown_field(tmp_path):
    p = tmp_path / "seed.yaml"
    p.write_text(
        "kind: {code: rdbms, name: X}\n"
        "flavor: {code: c, name: n, versions: []}\n"
        "types: []\n"
        "bogus: true\n"
    )
    with pytest.raises(Exception):
        load_seed_file(p)


def test_seed_param_spec_accepts_min_max():
    spec = SeedParamSpec(type="int", required=False, default=None, min=1, max=1000)
    assert spec.min == 1
    assert spec.max == 1000


def test_seed_param_spec_defaults_min_max_to_none():
    spec = SeedParamSpec(type="int", required=False, default=None)
    assert spec.min is None
    assert spec.max is None
