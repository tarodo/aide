from typing import Literal

from backend.models.engine import Engine

Side = Literal["after", "before"]

_JSON_FORMATS = {"json"}


class EnvelopeResolver:
    """Read-only helper that resolves source field names to Kafka payload paths
    given a CDC engine attached to the upstream link.

    If `cdc_engine` is None, paths pass through unchanged (i.e. the source is
    not a Kafka envelope).
    """

    def __init__(self, cdc_engine: Engine | None, kafka_format: str) -> None:
        self._engine = cdc_engine
        self._format = (kafka_format or "").lower()
        self._template: dict[str, str] = {}
        if cdc_engine is not None:
            tmpl = getattr(cdc_engine, "envelope_template", None) or {}
            self._template = {k: str(v) for k, v in tmpl.items() if isinstance(v, str)}

    def _wrap(self, dotted: str) -> str:
        if self._engine is None:
            return dotted
        if self._format in _JSON_FORMATS:
            return f"get_json_object(payload, '$.{dotted}')"
        return f"payload.{dotted}"

    def _segment(self, key: str, default: str) -> str:
        return self._template.get(key, default)

    def path_for(self, name: str, side: Side = "after") -> str:
        if self._engine is None:
            return name
        side_key = "after_path" if side == "after" else "before_path"
        side_path = self._segment(side_key, side)
        return self._wrap(f"{side_path}.{name}")

    def op_path(self) -> str:
        if self._engine is None:
            return "op"
        return self._wrap(self._segment("op_path", "op"))

    def ts_path(self) -> str:
        if self._engine is None:
            return "ts"
        # Debezium calls this ts_ms_path; OGG calls it ts_path. Try both.
        path = self._template.get("ts_ms_path") or self._template.get("ts_path") or "ts"
        return self._wrap(path)
