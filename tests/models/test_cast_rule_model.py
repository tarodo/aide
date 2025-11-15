import pytest

from backend.models.cast_rule import CastRule, CastSafety, CastSafetyType


class TestCastSafetyType:
    @pytest.fixture
    def type_decorator(self) -> CastSafetyType:
        return CastSafetyType()

    # Tests for process_bind_param
    @pytest.mark.parametrize(
        "input_value, expected_output",
        [
            (None, None),
            (CastSafety.IMPLICIT, "IMPLICIT"),
            (CastSafety.SAFE, "SAFE"),
            (CastSafety.UNSAFE, "UNSAFE"),
            ("implicit", "IMPLICIT"),
            ("safe", "SAFE"),
            ("unsafe", "UNSAFE"),
            ("IMPLICIT", "IMPLICIT"),
            ("SAFE", "SAFE"),
            ("UNSAFE", "UNSAFE"),
            (123, 123),  # Should pass through non-string/enum values
        ],
    )
    def test_process_bind_param(
        self, type_decorator: CastSafetyType, input_value, expected_output
    ):
        """Test conversion from Python types to DB-compatible types."""
        assert type_decorator.process_bind_param(input_value, None) == expected_output

    def test_process_bind_param_invalid_string_value(
        self, type_decorator: CastSafetyType
    ):
        """Test that an invalid string value is converted to uppercase."""
        # The current implementation is permissive and will just uppercase it.
        assert type_decorator.process_bind_param("invalid", None) == "INVALID"

    # Tests for process_result_value
    @pytest.mark.parametrize(
        "input_value, expected_output",
        [
            (None, None),
            ("IMPLICIT", CastSafety.IMPLICIT),
            ("SAFE", CastSafety.SAFE),
            ("UNSAFE", CastSafety.UNSAFE),
            ("implicit", CastSafety.IMPLICIT),
            ("safe", CastSafety.SAFE),
            ("unsafe", CastSafety.UNSAFE),
            (CastSafety.SAFE, CastSafety.SAFE),  # Already an enum
        ],
    )
    def test_process_result_value(
        self, type_decorator: CastSafetyType, input_value, expected_output
    ):
        """Test conversion from DB types to Python enum."""
        assert type_decorator.process_result_value(input_value, None) == expected_output

    def test_process_result_value_invalid_string(self, type_decorator: CastSafetyType):
        """Test that an invalid string from the DB raises an error."""
        with pytest.raises((KeyError, ValueError)):
            type_decorator.process_result_value("INVALID_FROM_DB", None)


class TestCastRuleModel:
    def test_repr(self):
        """Test the __repr__ method of the CastRule model."""
        import uuid

        rule = CastRule(
            id=uuid.uuid4(),
            source_data_type_id=uuid.uuid4(),
            target_data_type_id=uuid.uuid4(),
        )
        expected_repr = (
            f"CastRule(id={rule.id}, "
            f"source={rule.source_data_type_id}, "
            f"target={rule.target_data_type_id})"
        )
        assert repr(rule) == expected_repr
