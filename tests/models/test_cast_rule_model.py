from backend.models.cast_rule import CastRule


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
