"""
constraint_validator.py — DomainConstraintValidator

Validates filter conditions and dimension values against domain-defined
constraints before any SQL is generated. Catches impossible queries early
(e.g. FICO=950, product_type="STUDENT_LOAN") so the user gets a clear error
message rather than a silent empty result.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader

logger = logging.getLogger(__name__)

# Constraints encoded here are the source of truth; they match the YAML
# allowed_values and the known business rules for this platform.

_FICO_MIN = 300
_FICO_MAX = 850

_KNOWN_PRODUCT_TYPES = frozenset({
    "PERSONAL", "MORTGAGE", "CREDIT_CARD", "AUTO", "STUDENT",
    "PERSONAL_LOAN", "HOME_LOAN",
    # short aliases
    "PL", "CC", "MTG",
})

_KNOWN_LOAN_STATUSES = frozenset({
    "CURRENT", "DELINQUENT", "DEFAULT", "CHARGED_OFF", "PAID_OFF",
    "ACTIVE", "CLOSED", "30DPD", "60DPD", "90DPD",
})

_KNOWN_STATES = frozenset({
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC",
})


@dataclass
class ConstraintViolation:
    field: str
    value: Any
    reason: str


class DomainConstraintValidator:
    """Validate filter conditions before query execution.

    Example::

        validator = DomainConstraintValidator()
        violations = validator.validate_filters({
            "fico_score": 950,         # invalid — max is 850
            "state": "XX",             # invalid — unknown state code
            "product_type": "PERSONAL_LOAN",  # valid
        })
    """

    def __init__(self, loader: Optional[SemanticLayerLoader] = None) -> None:
        self._loader = loader or get_loader()

    def validate_filters(self, filters: Dict[str, Any]) -> List[ConstraintViolation]:
        """Validate a dict of {field → value} filter conditions.

        Returns a list of violations (empty means all valid).
        """
        violations: List[ConstraintViolation] = []

        for field, value in filters.items():
            field_lower = field.lower()

            if "fico" in field_lower or field_lower in ("credit_score",):
                v = self._check_fico(field, value)
                if v:
                    violations.append(v)

            elif field_lower in ("product_type", "product_code", "product"):
                v = self._check_enum(field, value, _KNOWN_PRODUCT_TYPES, "product type")
                if v:
                    violations.append(v)

            elif field_lower in ("loan_status", "status_cd", "acct_status"):
                v = self._check_enum(field, value, _KNOWN_LOAN_STATUSES, "loan status")
                if v:
                    violations.append(v)

            elif field_lower == "state":
                v = self._check_enum(field, value, _KNOWN_STATES, "US state code")
                if v:
                    violations.append(v)

            elif field_lower in ("delinquency_rate", "charge_off_rate", "approval_rate"):
                v = self._check_rate(field, value)
                if v:
                    violations.append(v)

        return violations

    def validate_metric_value(
        self, field: str, value: Any
    ) -> Optional[ConstraintViolation]:
        """Validate a single result value (post-execution check)."""
        field_lower = field.lower()
        if "fico" in field_lower:
            return self._check_fico(field, value)
        if "rate" in field_lower:
            return self._check_rate(field, value)
        return None

    # ------------------------------------------------------------------
    # Internal validators
    # ------------------------------------------------------------------

    def _check_fico(self, field: str, value: Any) -> Optional[ConstraintViolation]:
        try:
            v = int(value)
        except (TypeError, ValueError):
            return None
        if not (_FICO_MIN <= v <= _FICO_MAX):
            return ConstraintViolation(
                field=field,
                value=value,
                reason=f"FICO score must be between {_FICO_MIN} and {_FICO_MAX}; got {v}",
            )
        return None

    def _check_enum(
        self, field: str, value: Any, allowed: frozenset, label: str
    ) -> Optional[ConstraintViolation]:
        if value is None:
            return None
        norm = str(value).upper().strip()
        if norm not in allowed:
            return ConstraintViolation(
                field=field,
                value=value,
                reason=f"Unknown {label} '{value}'. Known values: {sorted(allowed)[:10]}…",
            )
        return None

    def _check_rate(self, field: str, value: Any) -> Optional[ConstraintViolation]:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        # Rates in this platform are stored as decimals (0–1) or percentages (0–100)
        # Allow up to 100 but flag impossible negatives
        if v < -1.0:
            return ConstraintViolation(
                field=field,
                value=value,
                reason=f"Rate '{field}' cannot be negative; got {v}",
            )
        return None
