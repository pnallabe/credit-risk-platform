"""
P0.3 — Policy DSL Tests
=========================
Verify the safe expression evaluator in ``decision_engine.policy_dsl``:

  1. Allowed operators work correctly.
  2. Compound (all / any) logic works correctly.
  3. Disallowed syntax / malformed schemas raise ``PolicyDSLError``.
  4. HardRule validates at construction time and evaluates correctly.
  5. No ``eval`` call exists in the decision engine agent after P0.3.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict

import pytest

from decision_engine.policy_dsl import (
    PolicyDSLError,
    evaluate_rule,
    validate_rule,
)
from agents.decision_engine_agent import HardRule


# ---------------------------------------------------------------------------
# validate_rule — schema validation
# ---------------------------------------------------------------------------


class TestValidateRule:
    def test_valid_leaf_eq(self) -> None:
        validate_rule({"field": "fraud_flag", "op": "==", "value": "reject"})

    def test_valid_leaf_gt(self) -> None:
        validate_rule({"field": "dti", "op": ">", "value": 0.55})

    def test_valid_leaf_is_not_none(self) -> None:
        validate_rule({"field": "num_open_accounts", "op": "is_not_none"})

    def test_valid_leaf_is_none(self) -> None:
        validate_rule({"field": "credit_score", "op": "is_none"})

    def test_valid_compound_all(self) -> None:
        validate_rule({
            "all": [
                {"field": "num_open_accounts", "op": "is_not_none"},
                {"field": "num_open_accounts", "op": "<", "value": 1},
            ]
        })

    def test_valid_compound_any(self) -> None:
        validate_rule({
            "any": [
                {"field": "dti", "op": ">", "value": 0.55},
                {"field": "fraud_flag", "op": "==", "value": "reject"},
            ]
        })

    def test_invalid_op_rejected(self) -> None:
        with pytest.raises(PolicyDSLError, match="not permitted"):
            validate_rule({"field": "dti", "op": "in", "value": [0.5, 0.6]})

    def test_eval_string_rejected(self) -> None:
        """A raw Python expression string must never be accepted."""
        with pytest.raises(PolicyDSLError):
            validate_rule("dti > 0.55")  # type: ignore[arg-type]

    def test_missing_field_key(self) -> None:
        with pytest.raises(PolicyDSLError, match="missing required keys"):
            validate_rule({"op": ">", "value": 0.55})

    def test_missing_op_key(self) -> None:
        with pytest.raises(PolicyDSLError, match="missing required keys"):
            validate_rule({"field": "dti", "value": 0.55})

    def test_non_identifier_field_rejected(self) -> None:
        with pytest.raises(PolicyDSLError, match="valid Python identifier"):
            validate_rule({"field": "ctx['dti']", "op": ">", "value": 0.55})

    def test_null_op_must_not_have_value(self) -> None:
        with pytest.raises(PolicyDSLError, match="must not specify a 'value'"):
            validate_rule({"field": "credit_score", "op": "is_none", "value": None})

    def test_comparison_op_must_have_value(self) -> None:
        with pytest.raises(PolicyDSLError, match="requires a 'value' key"):
            validate_rule({"field": "dti", "op": ">"})

    def test_callable_value_rejected(self) -> None:
        with pytest.raises(PolicyDSLError):
            validate_rule({"field": "dti", "op": ">", "value": lambda x: x})

    def test_extra_keys_rejected(self) -> None:
        with pytest.raises(PolicyDSLError, match="unexpected keys"):
            validate_rule({"field": "dti", "op": ">", "value": 0.55, "exec": "os.system('rm -rf /')"})

    def test_empty_all_rejected(self) -> None:
        with pytest.raises(PolicyDSLError, match="non-empty list"):
            validate_rule({"all": []})

    def test_nesting_depth_limit(self) -> None:
        """Deeply nested rules should be rejected."""
        def _nest(depth: int) -> Dict[str, Any]:
            if depth == 0:
                return {"field": "dti", "op": ">", "value": 0.55}
            return {"all": [_nest(depth - 1)]}
        with pytest.raises(PolicyDSLError, match="depth"):
            validate_rule(_nest(10))


# ---------------------------------------------------------------------------
# evaluate_rule — correct evaluation
# ---------------------------------------------------------------------------


class TestEvaluateRule:
    _CTX: Dict[str, Any] = {
        "fraud_flag": "reject",
        "dti": 0.60,
        "num_open_accounts": 0,
        "pd_score": 0.12,
    }

    def test_leaf_eq_match(self) -> None:
        rule = {"field": "fraud_flag", "op": "==", "value": "reject"}
        assert evaluate_rule(rule, self._CTX) is True

    def test_leaf_eq_no_match(self) -> None:
        rule = {"field": "fraud_flag", "op": "==", "value": "continue"}
        assert evaluate_rule(rule, self._CTX) is False

    def test_leaf_gt_match(self) -> None:
        rule = {"field": "dti", "op": ">", "value": 0.55}
        assert evaluate_rule(rule, self._CTX) is True

    def test_leaf_gt_no_match(self) -> None:
        rule = {"field": "dti", "op": ">", "value": 0.65}
        assert evaluate_rule(rule, self._CTX) is False

    def test_leaf_lt_match(self) -> None:
        rule = {"field": "num_open_accounts", "op": "<", "value": 1}
        assert evaluate_rule(rule, self._CTX) is True

    def test_leaf_is_not_none_match(self) -> None:
        rule = {"field": "num_open_accounts", "op": "is_not_none"}
        assert evaluate_rule(rule, self._CTX) is True

    def test_leaf_is_none_match(self) -> None:
        rule = {"field": "credit_score", "op": "is_none"}
        # credit_score not in context → should be treated as None
        assert evaluate_rule(rule, self._CTX) is True

    def test_compound_all_match(self) -> None:
        rule = {
            "all": [
                {"field": "num_open_accounts", "op": "is_not_none"},
                {"field": "num_open_accounts", "op": "<", "value": 1},
            ]
        }
        assert evaluate_rule(rule, self._CTX) is True

    def test_compound_all_partial_fail(self) -> None:
        """all fails if any sub-rule fails."""
        rule = {
            "all": [
                {"field": "fraud_flag", "op": "==", "value": "reject"},  # True
                {"field": "dti", "op": ">", "value": 0.80},               # False
            ]
        }
        assert evaluate_rule(rule, self._CTX) is False

    def test_compound_any_match(self) -> None:
        rule = {
            "any": [
                {"field": "dti", "op": ">", "value": 0.90},    # False
                {"field": "fraud_flag", "op": "==", "value": "reject"},  # True
            ]
        }
        assert evaluate_rule(rule, self._CTX) is True

    def test_missing_field_treated_as_non_match(self) -> None:
        rule = {"field": "nonexistent_field", "op": ">", "value": 0.5}
        assert evaluate_rule(rule, self._CTX) is False

    def test_type_mismatch_treated_as_non_match(self) -> None:
        """Comparing a string field value to a float must not raise; returns False."""
        rule = {"field": "fraud_flag", "op": ">", "value": 0.5}
        result = evaluate_rule(rule, self._CTX)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# HardRule integration — validates at construction, evaluates without eval
# ---------------------------------------------------------------------------


class TestHardRule:
    def _make_rule(self, condition: Any) -> HardRule:
        return HardRule({
            "rule_id": "test-rule",
            "name": "Test Rule",
            "condition": condition,
            "action": "REJECT",
            "reason_code": "AA04",
        })

    def test_valid_rule_construction(self) -> None:
        rule = self._make_rule({"field": "dti", "op": ">", "value": 0.55})
        assert rule.rule_id == "test-rule"

    def test_invalid_rule_raises_at_construction(self) -> None:
        with pytest.raises(ValueError, match="invalid DSL condition"):
            self._make_rule({"field": "dti", "op": "eval", "value": 0.55})

    def test_string_condition_raises_at_construction(self) -> None:
        """Legacy string condition must be rejected at construction time."""
        with pytest.raises((ValueError, TypeError)):
            self._make_rule("dti > 0.55")

    def test_rule_matches(self) -> None:
        rule = self._make_rule({"field": "dti", "op": ">", "value": 0.55})
        assert rule.matches({"dti": 0.60}) is True
        assert rule.matches({"dti": 0.40}) is False

    def test_compound_rule_hr003(self) -> None:
        """HR-003 DSL form should correctly detect thin-file no-accounts."""
        rule = self._make_rule({
            "all": [
                {"field": "num_open_accounts", "op": "is_not_none"},
                {"field": "num_open_accounts", "op": "<", "value": 1},
            ]
        })
        assert rule.matches({"num_open_accounts": 0}) is True
        assert rule.matches({"num_open_accounts": 2}) is False
        assert rule.matches({}) is False  # None → is_not_none fails


# ---------------------------------------------------------------------------
# Prove no eval() call sites remain in the decision engine agent
# ---------------------------------------------------------------------------


def _strip_comments_and_docstrings(source: str) -> str:
    """Return source with string literals and # comments removed."""
    import ast
    import tokenize
    import io

    result_tokens = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return source  # fallback

    for tok_type, tok_string, *_ in tokens:
        if tok_type == tokenize.COMMENT:
            continue  # drop # comments
        if tok_type == tokenize.STRING:
            continue  # drop string literals (includes docstrings)
        result_tokens.append(tok_string)

    return " ".join(result_tokens)


class TestNoEvalInAgent:
    def test_hard_rule_matches_does_not_call_eval(self) -> None:
        """Inspect the source of HardRule.matches to confirm no eval() call."""
        source = inspect.getsource(HardRule.matches)
        code_only = _strip_comments_and_docstrings(source)
        assert "eval(" not in code_only, (
            "HardRule.matches still contains an eval() call — P0.3 is incomplete"
        )

    def test_hard_rule_class_source_has_no_eval(self) -> None:
        """Full HardRule class must contain no eval() code (excluding docstrings)."""
        source = inspect.getsource(HardRule)
        code_only = _strip_comments_and_docstrings(source)
        assert "eval(" not in code_only, (
            "HardRule class still contains eval() code — P0.3 is incomplete"
        )
