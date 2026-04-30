from backend.core import errors
from backend.core.exceptions import AppException

_ALLOWED: set[tuple[str, str, str]] = {
    ("cdc", "rdbms", "kafka"),
    ("compute", "kafka", "hive"),
    ("compute", "hive", "hive"),
}


def is_allowed(role: str, source_kind: str, target_kind: str) -> bool:
    return (role, source_kind, target_kind) in _ALLOWED


def assert_compatible(*, role: str, source_kind: str, target_kind: str) -> None:
    if not is_allowed(role, source_kind, target_kind):
        raise AppException(
            errors.ENGINE_INCOMPATIBLE_LINK,
            details={
                "engine_role": role,
                "source_kind": source_kind,
                "target_kind": target_kind,
            },
        )
