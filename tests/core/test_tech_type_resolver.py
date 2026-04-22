from pathlib import Path

import pytest

from backend.core.tech_type_resolver import TechTypeResolver

SAMPLE_YAML = """
mappings:
  - flavor: postgres14
    type_code: TIMESTAMP
    data_type_code: timestamp
  - flavor: postgres14
    type_code: STRING
    data_type_code: text
  - flavor: kafka_avro
    type_code: TIMESTAMP
    data_type_code: long
"""


@pytest.fixture
def resolver(tmp_path: Path) -> TechTypeResolver:
    path = tmp_path / "mappings.yaml"
    path.write_text(SAMPLE_YAML)
    return TechTypeResolver.from_yaml(path)


def test_resolve_found(resolver: TechTypeResolver):
    assert resolver.resolve("postgres14", "TIMESTAMP") == "timestamp"
    assert resolver.resolve("postgres14", "STRING") == "text"
    assert resolver.resolve("kafka_avro", "TIMESTAMP") == "long"


def test_resolve_unknown_flavor(resolver: TechTypeResolver):
    assert resolver.resolve("oracle", "TIMESTAMP") is None


def test_resolve_unknown_type_code(resolver: TechTypeResolver):
    assert resolver.resolve("postgres14", "UNKNOWN") is None


def test_duplicate_mapping_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("""
mappings:
  - flavor: postgres14
    type_code: TIMESTAMP
    data_type_code: timestamp
  - flavor: postgres14
    type_code: TIMESTAMP
    data_type_code: timestamptz
""")
    with pytest.raises(ValueError, match="Duplicate mapping"):
        TechTypeResolver.from_yaml(bad)
