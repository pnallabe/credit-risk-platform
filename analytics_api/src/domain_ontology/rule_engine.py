"""
rule_engine.py — BusinessRuleEngine

Evaluates OntologyRules against numeric or categorical values returned
by a query. Deliberately avoids Python ``eval()`` — expressions are
parsed into a restricted AST with only comparison and boolean operators.

Supported expression forms:
  - "value >= 0"
  - "value <= 100"
  - "0 <= value <= 100"
  - "300 <= value <= 850"
  - "true" / "false"
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from analytics_api.src.domain_ontology.concept import OntologyRule
from analytics_api.src.domain_ontology.ontology_parser import OntologyParser, get_ontology

logger = logging.getLogger(__name__)

# Compiled pattern for chained comparisons: "lo OP value OP hi"
_CHAIN = re.compile(
    r"^\s*(-?[\d.]+)\s*(<=|<|>=|>|==)\s*value\s*(<=|<|>=|>|==)\s*(-?[\d.]+)\s*$"
)
# Single comparison: "value OP number"
_SINGLE_LEFT = re.compile(r"^\s*value\s*(<=|<|>=|>|==)\s*(-?[\d.]+)\s*$")
# Single comparison: "number OP value"
_SINGLE_RIGHT = re.compile(r"^\s*(-?[\d.]+)\s*(<=|<|>=|>|==)\s*value\s*$")


def _compare(a: float, op: str, b: float) -> bool:
    return {
        "<=": a <= b,
        "<":  a < b,
        ">=": a >= b,
        ">":  a > b,
        "==": a == b,
    }[op]


def _eval_expression(expr: str, value: Any) -> bool:
    """Evaluate a restricted comparison expression against ``value``."""
    expr = expr.strip()
    if expr.lower() in ("true", ""):
        return True
    if expr.lower() == "false":
        return False

    try:
        v = float(value)
    except (TypeError, ValueError):
        # Cannot evaluate numeric expression against non-numeric value; skip
        return True

    # Chained: lo OP value OP hi
    m = _CHAIN.match(expr)
    if m:
        lo, op1, op2, hi = m.group(1), m.group(2), m.group(3), m.group(4)
        return _compare(float(lo), op1, v) and _compare(v, op2, float(hi))

    # value OP number
    m = _SINGLE_LEFT.match(expr)
    if m:
        op, num = m.group(1), m.group(2)
        return _compare(v, op, float(num))

    # number OP value
    m = _SINGLE_RIGHT.match(expr)
    if m:
        num, op = m.group(1), m.group(2)
        return _compare(float(num), op, v)

    logger.warning("RuleEngine: unrecognised expression '%s'", expr)
    return True


@dataclass
class RuleViolation:
    rule_id: str
    concept_name: str
    severity: str           # error | warning
    description: str
    actual_value: Any
    expression: str


class BusinessRuleEngine:
    """Validate query results against domain ontology rules.

    Example::

        engine = BusinessRuleEngine()
        violations = engine.validate_row(
            concept_name="Delinquency",
            row={"delinquency_rate": -2.5, "product_type": "PERSONAL"},
            metric_field="delinquency_rate",
        )
        # → [RuleViolation(rule_id="DLQ-R01", severity="error", ...)]
    """

    def __init__(self, parser: Optional[OntologyParser] = None) -> None:
        self._parser = parser or get_ontology()

    def validate_row(
        self,
        concept_name: str,
        row: Dict[str, Any],
        metric_field: str,
        inherited: bool = True,
    ) -> List[RuleViolation]:
        """Evaluate all rules for a concept against a single result row."""
        value = row.get(metric_field)
        rules = self._parser.get_rules(concept_name, inherited=inherited)
        violations: List[RuleViolation] = []
        for rule in rules:
            if not _eval_expression(rule.expression, value):
                violations.append(
                    RuleViolation(
                        rule_id=rule.id,
                        concept_name=concept_name,
                        severity=rule.severity,
                        description=rule.description,
                        actual_value=value,
                        expression=rule.expression,
                    )
                )
        return violations

    def validate_rows(
        self,
        concept_name: str,
        rows: List[Dict[str, Any]],
        metric_field: str,
        inherited: bool = True,
    ) -> List[RuleViolation]:
        """Evaluate rules across all rows. Returns all violations found."""
        all_violations: List[RuleViolation] = []
        for row in rows:
            all_violations.extend(
                self.validate_row(concept_name, row, metric_field, inherited)
            )
        return all_violations

    def has_errors(self, violations: List[RuleViolation]) -> bool:
        return any(v.severity == "error" for v in violations)
