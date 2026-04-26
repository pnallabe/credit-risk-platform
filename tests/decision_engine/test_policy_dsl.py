"""
Smoke tests for decision_engine/policy_dsl.py
"""
from __future__ import annotations

import pytest

from decision_engine.policy_dsl import (
    PolicyDSLError,
    evaluate_rule,
    validate_rule,
)


def test_validate_leaf_rule():
    validate_rule({"field": "credit_score", "op": ">=", "value": 620})


def test_validate_all_compound():
    validate_rule({
        "all": [
            {"field": "credit_score", "op": ">=", "value": 620},
            {"field": "dti", "op": "<=", "value": 0.45},
        ]
    })


def test_validate_any_compound():
    validate_rule({
        "any": [
            {"field": "credit_score", "op": ">=", "value": 700},
            {"field": "collateral_value", "op": ">", "value": 10000},
        ]
    })


def test_validate_missing_field_raises():
    with pytest.raises(PolicyDSLError):
        validate_rule({"op": ">=", "value": 620})


def test_validate_unknown_op_raises():
    with pytest.raises(PolicyDSLError):
        validate_rule({"field": "credit_score", "op": "EVIL_OP", "value": 620})


def test_validate_non_dict_raises():
    with pytest.raises(PolicyDSLError):
        validate_rule("not a dict")


def test_validate_nested_compound():
    validate_rule({
        "all": [
            {"field": "credit_score", "op": ">=", "value": 620},
            {"any": [
                {"field": "income", "op": ">", "value": 50000},
                {"field": "collateral", "op": ">", "value": 30000},
            ]},
        ]
    })


def test_evaluate_leaf_gte_pass():
    rule = {"field": "credit_score", "op": ">=", "value": 620}
    assert evaluate_rule(rule, {"credit_score": 700}) is True


def test_evaluate_leaf_gte_fail():
    rule = {"field": "credit_score", "op": ">=", "value": 620}
    assert evaluate_rule(rule, {"credit_score": 500}) is False


def test_evaluate_leaf_lt():
    rule = {"field": "dti", "op": "<", "value": 0.45}
    assert evaluate_rule(rule, {"dti": 0.30}) is True
    assert evaluate_rule(rule, {"dti": 0.60}) is False


def test_evaluate_all_conjunction():
    rule = {
        "all": [
            {"field": "credit_score", "op": ">=", "value": 620},
            {"field": "dti", "op": "<", "value": 0.45},
        ]
    }
    assert evaluate_rule(rule, {"credit_score": 700, "dti": 0.30}) is True
    assert evaluate_rule(rule, {"credit_score": 700, "dti": 0.50}) is False


def test_evaluate_any_disjunction():
    rule = {
        "any": [
            {"field": "credit_score", "op": ">=", "value": 700},
            {"field": "collateral", "op": ">", "value": 10000},
        ]
    }
    assert evaluate_rule(rule, {"credit_score": 750, "collateral": 0}) is True
    assert evaluate_rule(rule, {"credit_score": 600, "collateral": 20000}) is True
    assert evaluate_rule(rule, {"credit_score": 600, "collateral": 0}) is False


def test_evaluate_missing_field_returns_false():
    rule = {"field": "nonexistent_field", "op": ">=", "value": 500}
    assert evaluate_rule(rule, {}) is False


def test_evaluate_is_none():
    rule = {"field": "collateral", "op": "is_none"}
    assert evaluate_rule(rule, {"collateral": None}) is True
    assert evaluate_rule(rule, {"collateral": 1000}) is False


def test_evaluate_is_not_none():
    rule = {"field": "collateral", "op": "is_not_none"}
    assert evaluate_rule(rule, {"collateral": 1000}) is True
    assert evaluate_rule(rule, {"collateral": None}) is False


def test_evaluate_eq():
    rule = {"field": "status", "op": "==", "value": "APPROVED"}
    assert evaluate_rule(rule, {"status": "APPROVED"}) is True
    assert evaluate_rule(rule, {"status": "DENIED"}) is False


# ---------------------------------------------------------------------------
# validate_rule edge cases
# ---------------------------------------------------------------------------

def test_validate_depth_exceeded():
    """A rule nested more than 8 levels must raise PolicyDSLError."""
    def _nest(depth):
        if depth == 0:
            return {"field": "x", "op": ">=", "value": 1}
        return {"all": [_nest(depth - 1)]}
    with pytest.raises(PolicyDSLError):
        validate_rule(_nest(9))


def test_validate_compound_extra_keys_raises():
    with pytest.raises(PolicyDSLError):
        validate_rule({"all": [{"field": "x", "op": ">=", "value": 1}], "extra": True})


def test_validate_compound_empty_list_raises():
    with pytest.raises(PolicyDSLError):
        validate_rule({"all": []})


def test_validate_invalid_identifier_raises():
    with pytest.raises(PolicyDSLError):
        validate_rule({"field": "bad-field!", "op": ">=", "value": 1})


def test_validate_null_op_with_value_raises():
    with pytest.raises(PolicyDSLError):
        validate_rule({"field": "x", "op": "is_none", "value": 1})


def test_validate_comparison_op_without_value_raises():
    with pytest.raises(PolicyDSLError):
        validate_rule({"field": "x", "op": ">="})


def test_validate_non_scalar_value_raises():
    with pytest.raises(PolicyDSLError):
        validate_rule({"field": "x", "op": ">=", "value": [1, 2, 3]})


def test_validate_extra_leaf_keys_raises():
    with pytest.raises(PolicyDSLError):
        validate_rule({"field": "x", "op": ">=", "value": 1, "bogus": True})


# ---------------------------------------------------------------------------
# _migrate_legacy_condition
# ---------------------------------------------------------------------------

def test_migrate_legacy_condition_simple():
    from decision_engine.policy_dsl import _migrate_legacy_condition
    result = _migrate_legacy_condition("credit_score >= 620")
    assert result == {"field": "credit_score", "op": ">=", "value": 620}


def test_migrate_legacy_condition_string_value():
    from decision_engine.policy_dsl import _migrate_legacy_condition
    result = _migrate_legacy_condition("status == 'employed'")
    assert result == {"field": "status", "op": "==", "value": "employed"}


def test_migrate_legacy_condition_unrecognised_returns_none():
    from decision_engine.policy_dsl import _migrate_legacy_condition
    result = _migrate_legacy_condition("x + y > 10 or z < 5")
    assert result is None
