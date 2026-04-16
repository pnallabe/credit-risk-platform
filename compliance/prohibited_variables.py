"""
compliance/prohibited_variables.py
=====================================
Registry of ECOA / Fair Housing Act / FCRA prohibited variables and
their known proxy features.

Public API
----------
>>> from compliance.prohibited_variables import check_for_prohibited_variables
>>> check_for_prohibited_variables({"race": "white", "credit_score": 720})
# raises ProhibitedVariableViolation
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Set


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Direct prohibited basis variables (ECOA §202.2(z), Fair Housing Act)
PROHIBITED_VARIABLES: FrozenSet[str] = frozenset({
    "race", "color", "religion", "national_origin", "sex", "gender",
    "marital_status", "age", "familial_status", "disability",
    "immigration_status", "citizenship_status", "sexual_orientation",
    "gender_identity", "receipt_of_public_assistance",
    # common variants / misspellings
    "ethnicity", "ancestry", "country_of_birth", "birthplace",
    "religion_type", "sex_type",
})

#: Proxy variables that correlate with protected class at census-tract level
PROXY_VARIABLE_MAP: Dict[str, str] = {
    "zip_code":              "national_origin / race (redlining proxy)",
    "census_tract":          "race / national_origin",
    "neighborhood_code":     "race / national_origin",
    "last_name_score":       "national_origin / race (surname proxy)",
    "language":              "national_origin",
    "maiden_name":           "sex / marital_status",
    "social_club_membership": "religion / national_origin",
}


@dataclass
class ProhibitedVariableViolation(ValueError):
    """Raised when a prohibited or proxy variable is found in the feature set."""
    variable: str
    basis: str  # which protected class it maps to

    def __str__(self) -> str:
        return (
            f"Prohibited variable '{self.variable}' detected "
            f"(protected basis: {self.basis}). "
            "Remove this feature before submitting to the decision engine."
        )


def check_for_prohibited_variables(features: Dict) -> None:
    """Raise ProhibitedVariableViolation on the first prohibited or proxy
    feature key found in *features*.  Keys are compared case-insensitively.

    Parameters
    ----------
    features : dict
        Feature dictionary (or any mapping whose keys are feature names).

    Raises
    ------
    ProhibitedVariableViolation
    """
    lowered = {k.lower(): k for k in features}
    for key_lower, key_orig in lowered.items():
        if key_lower in PROHIBITED_VARIABLES:
            raise ProhibitedVariableViolation(
                variable=key_orig,
                basis=key_lower,
            )
        if key_lower in PROXY_VARIABLE_MAP:
            raise ProhibitedVariableViolation(
                variable=key_orig,
                basis=PROXY_VARIABLE_MAP[key_lower],
            )
