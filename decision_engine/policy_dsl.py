"""
decision_engine.policy_dsl — Safe Policy Rule Evaluator
=========================================================
Replaces the ``eval()``-based rule evaluator in the decision engine with a
restricted, auditable DSL that:

* Rejects any Python that is not a pure field comparison.
* Supports compound ``all`` / ``any`` logic.
* Is deterministic, serialisable, and loggable (rule_id + inputs used +
  outcome).
* Has zero arbitrary code execution surface — ``eval`` and ``exec`` are
  never called.

Rule Schema (JSON / YAML)
--------------------------
Leaf node (field comparison):

    { "field": str, "op": str, "value": <scalar> }

Supported ``op`` values
~~~~~~~~~~~~~~~~~~~~~~~
  ==   !=   >   <   >=   <=
  is_none        (field value IS None)
  is_not_none    (field value IS NOT None)

Compound nodes:

    { "all": [ <rule>, ... ] }   # all sub-rules must match  (AND)
    { "any": [ <rule>, ... ] }   # at least one must match  (OR)

Example
-------
Old eval-style:
    condition: "num_open_accounts is not None and num_open_accounts < 1"

New DSL:
    condition:
      all:
        - { field: num_open_accounts, op: is_not_none }
        - { field: num_open_accounts, op: "<", value: 1 }

Public API
----------
>>> from decision_engine.policy_dsl import evaluate_rule, validate_rule
>>> rule = {"field": "dti", "op": ">", "value": 0.55}
>>> validate_rule(rule)  # raises ValueError if malformed
>>> evaluate_rule(rule, ctx={"dti": 0.60})  # returns True
"""

from __future__ import annotations

import logging
import operator
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed comparison operators
# ---------------------------------------------------------------------------

_OP_MAP: Dict[str, Any] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">":  operator.gt,
    "<":  operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}

_NULL_OPS: Set[str] = {"is_none", "is_not_none"}
_ALL_OPS: Set[str] = set(_OP_MAP.keys()) | _NULL_OPS


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class PolicyDSLError(ValueError):
    """Raised when a rule node does not conform to the permitted DSL schema."""


def validate_rule(rule: Any, *, _depth: int = 0) -> None:
    """Recursively validate *rule* against the DSL schema.

    Raises ``PolicyDSLError`` with a descriptive message on any violation.
    Allowed shapes:
      - ``{"field": str, "op": str, "value": ...}`` leaf comparison
      - ``{"all": [...]}`` conjunction
      - ``{"any": [...]}`` disjunction

    Parameters
    ----------
    rule:
        The rule node to validate.  Must be a dict.

    Raises
    ------
    PolicyDSLError
        If the rule contains unsupported operators, missing required keys,
        disallowed field names, or uses forbidden Python constructs.
    """
    if _depth > 8:
        raise PolicyDSLError("Rule nesting depth exceeds limit (8)")

    if not isinstance(rule, dict):
        raise PolicyDSLError(f"Rule node must be a dict, got {type(rule).__name__!r}")

    keys = set(rule.keys())

    # Compound node
    if "all" in keys or "any" in keys:
        extra = keys - {"all", "any"}
        if extra:
            raise PolicyDSLError(f"Compound rule must only have 'all' or 'any' key; found: {extra}")
        compound_key = "all" if "all" in keys else "any"
        sub_rules = rule[compound_key]
        if not isinstance(sub_rules, list) or not sub_rules:
            raise PolicyDSLError(f"'{compound_key}' must be a non-empty list")
        for sub in sub_rules:
            validate_rule(sub, _depth=_depth + 1)
        return

    # Leaf node
    required = {"field", "op"}
    missing = required - keys
    if missing:
        raise PolicyDSLError(f"Leaf rule is missing required keys: {missing}")

    field = rule["field"]
    op = rule["op"]

    if not isinstance(field, str) or not field.isidentifier():
        raise PolicyDSLError(
            f"'field' must be a valid Python identifier, got {field!r}"
        )

    if op not in _ALL_OPS:
        raise PolicyDSLError(
            f"Operator {op!r} is not permitted.  "
            f"Allowed: {sorted(_ALL_OPS)}"
        )

    if op in _NULL_OPS and "value" in rule:
        raise PolicyDSLError(
            f"Null-check operator {op!r} must not specify a 'value'"
        )

    if op not in _NULL_OPS and "value" not in rule:
        raise PolicyDSLError(
            f"Comparison operator {op!r} requires a 'value' key"
        )

    if "value" in rule:
        val = rule["value"]
        if not isinstance(val, (int, float, str, bool, type(None))):
            raise PolicyDSLError(
                f"Rule 'value' must be a scalar (int/float/str/bool/None), "
                f"got {type(val).__name__!r}"
            )

    # Reject any extra keys
    allowed_leaf_keys = {"field", "op", "value"}
    extra_keys = keys - allowed_leaf_keys
    if extra_keys:
        raise PolicyDSLError(f"Leaf rule contains unexpected keys: {extra_keys}")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_rule(
    rule: Dict[str, Any],
    ctx: Dict[str, Any],
    *,
    rule_id: Optional[str] = None,
) -> bool:
    """Evaluate *rule* against *ctx* and return a boolean outcome.

    All evaluation is done with Python builtins and the ``operator`` module —
    no ``eval`` or ``exec`` is ever called.

    Parameters
    ----------
    rule:
        A validated DSL rule node.
    ctx:
        Flat dict of field name → field value representing the applicant
        context (model scores merged with raw feature values).
    rule_id:
        Optional identifier used in debug logs.

    Returns
    -------
    bool
        ``True`` if the rule matches the context; ``False`` otherwise.
    """
    # Compound: all (AND)
    if "all" in rule:
        result = all(
            evaluate_rule(sub, ctx, rule_id=rule_id) for sub in rule["all"]
        )
        logger.debug("rule_id=%s all=%s", rule_id, result)
        return result

    # Compound: any (OR)
    if "any" in rule:
        result = any(
            evaluate_rule(sub, ctx, rule_id=rule_id) for sub in rule["any"]
        )
        logger.debug("rule_id=%s any=%s", rule_id, result)
        return result

    # Leaf
    field: str = rule["field"]
    op: str = rule["op"]
    field_value = ctx.get(field)  # None if not in context

    if op == "is_none":
        result = field_value is None
    elif op == "is_not_none":
        result = field_value is not None
    else:
        if field_value is None:
            # A missing field cannot satisfy a comparison — treat as non-match
            result = False
        else:
            try:
                result = bool(_OP_MAP[op](field_value, rule["value"]))
            except TypeError:
                # Type mismatch (e.g. comparing str to float) — treat as non-match
                result = False

    logger.debug(
        "rule_id=%s field=%s op=%s value=%r field_value=%r result=%s",
        rule_id,
        field,
        op,
        rule.get("value"),
        field_value,
        result,
    )
    return result


# ---------------------------------------------------------------------------
# Migration helper: convert legacy string condition (best-effort)
# ---------------------------------------------------------------------------

def _migrate_legacy_condition(condition: str) -> Optional[Dict[str, Any]]:
    """
    Best-effort migration of a simple legacy ``eval``-style condition string
    to the safe DSL format.  Returns ``None`` if the pattern is not recognised.

    Only handles patterns safe to migrate automatically:
      "field op value"            → leaf node
      "field op value and ..."    → ``{"all": [...]}``

    This function is intentionally limited — complex expressions must be
    migrated manually.
    """
    import re

    # Single comparison: "fraud_flag == 'reject'"
    single_pat = re.compile(
        r"^(\w+)\s+(==|!=|>|<|>=|<=)\s+"
        r"(?:'([^']*)'|\"([^\"]*)\"|(\d+(?:\.\d+)?)|True|False|None)$"
    )

    def _parse_value(raw: str) -> Any:
        if raw in ("True", "true"):
            return True
        if raw in ("False", "false"):
            return False
        if raw in ("None", "null"):
            return None
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            pass
        return raw  # string

    condition = condition.strip()
    m = single_pat.match(condition)
    if m:
        field = m.group(1)
        op = m.group(2)
        raw_val = next(g for g in m.groups()[2:] if g is not None)
        return {"field": field, "op": op, "value": _parse_value(raw_val)}

    return None
