"""
compliance/adverse_action.py
============================
Reg B / ECOA adverse action data model and FCRA reason code mappings.

Public API
----------
>>> from compliance.adverse_action import (
...     REG_B_REASON_CODES,
...     AdverseActionNotice,
...     map_shap_factors_to_reg_b_codes,
...     select_form_type,
... )
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# Reg B reason code mapping (CFPB Model Form C-1 language)
# ---------------------------------------------------------------------------

REG_B_REASON_CODES: Dict[str, str] = {
    # Core FCRA codes (matching REASON_CODE_DESCRIPTIONS in decision_engine/engine.py)
    "AA01": "High probability of default based on credit history",
    "AA02": "Unable to verify information provided",
    "AA03": "Insufficient credit history",
    "AA04": "Debt-to-income ratio too high",
    "AA05": "Application requires additional review",
    # SHAP-derived factor codes
    "SHAP_PAYMENT_HISTORY": "Delinquent past or present credit obligations with others",
    "SHAP_UTILIZATION":     "Proportion of balances to credit limits too high",
    "SHAP_DTI":             "Amount of monthly debt payments in relation to monthly income",
    "SHAP_ACCOUNT_AGE":     "Length of time accounts have been established",
    "SHAP_NUM_DEROG":       "Number of derogatory public records",
    "SHAP_EMPLOYMENT":      "Unable to verify employment information",
    "SHAP_INCOME":          "Income insufficient for amount of credit requested",
    "SHAP_CREDIT_SCORE":    "Credit score below minimum threshold",
    # Compliance-gate derived codes
    "COMP_MLA":      "Military Lending Act \u2014 interest rate cap exceeded",
    "COMP_STATE_APR": "State usury limit \u2014 proposed rate exceeds state maximum",
    "COMP_FRAUD":    "Unable to verify identity",
}


# ---------------------------------------------------------------------------
# SHAP feature name → Reg B code mapping
# ---------------------------------------------------------------------------

_SHAP_FEATURE_MAP: Dict[str, str] = {
    # Payment history / delinquency
    "payment_history":              "SHAP_PAYMENT_HISTORY",
    "months_since_last_delinquency": "SHAP_PAYMENT_HISTORY",
    "num_derogatory_marks":         "SHAP_NUM_DEROG",
    "derogatory_marks":             "SHAP_NUM_DEROG",
    # Utilization
    "credit_utilization":           "SHAP_UTILIZATION",
    "utilization_ratio":            "SHAP_UTILIZATION",
    # DTI
    "debt_to_income_ratio":         "SHAP_DTI",
    "dti":                          "SHAP_DTI",
    "monthly_debt_payments":        "SHAP_DTI",
    # Account age / history length
    "account_age":                  "SHAP_ACCOUNT_AGE",
    "credit_history_length":        "SHAP_ACCOUNT_AGE",
    "num_open_accounts":            "SHAP_ACCOUNT_AGE",
    # Employment
    "employment_status":            "SHAP_EMPLOYMENT",
    "employer_tenure_months":       "SHAP_EMPLOYMENT",
    # Income
    "annual_income":                "SHAP_INCOME",
    "monthly_income":               "SHAP_INCOME",
    # Credit score
    "credit_score":                 "SHAP_CREDIT_SCORE",
    "pd_score":                     "SHAP_CREDIT_SCORE",
    # Fraud
    "fraud_probability":            "COMP_FRAUD",
}


def map_shap_factors_to_reg_b_codes(shap_top_negative: List[Dict[str, Any]]) -> List[str]:
    """Map SHAP top-negative factors to Reg B adverse action codes.

    Parameters
    ----------
    shap_top_negative:
        List of dicts with keys ``feature``, ``shap_value``, ``direction``.
        Typically the ``top_negative_factors`` from ``ExplanationResult``.

    Returns
    -------
    list[str]
        Up to 4 Reg B codes, ordered by ``|shap_value|`` descending.
        Falls back to ``"AA01"`` for unmapped features.
    """
    # Sort by absolute shap_value descending
    sorted_factors = sorted(
        shap_top_negative,
        key=lambda f: abs(f.get("shap_value", 0.0)),
        reverse=True,
    )

    codes: List[str] = []
    seen: set[str] = set()
    for factor in sorted_factors:
        feature = str(factor.get("feature", "")).lower()
        code = _SHAP_FEATURE_MAP.get(feature, "AA01")
        if code not in seen:
            seen.add(code)
            codes.append(code)
        if len(codes) >= 4:
            break

    return codes


# ---------------------------------------------------------------------------
# Form-type selector
# ---------------------------------------------------------------------------

def select_form_type(context: Literal["denial", "counter_offer", "incomplete"]) -> str:
    """Return the CFPB Model Form designator for the given decisioning context.

    Parameters
    ----------
    context:
        ``"denial"``       → C-1 (credit denial)
        ``"counter_offer"`` → C-2 (credit approval with different terms)
        ``"incomplete"``   → C-3 (incomplete application)

    Returns
    -------
    str — one of ``"C-1"``, ``"C-2"``, ``"C-3"``
    """
    mapping = {
        "denial":       "C-1",
        "counter_offer": "C-2",
        "incomplete":   "C-3",
    }
    return mapping.get(context, "C-1")


# ---------------------------------------------------------------------------
# AdverseActionNotice dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdverseActionNotice:
    """Immutable data model for a Reg B adverse action notice.

    All fields are strings or primitives for easy JSON serialisation.
    ``reason_codes`` and ``reason_texts`` are parallel lists of at most 4 items.
    """

    notice_id: str
    application_id: str
    tenant_id: str
    applicant_name: str
    creditor_name: str
    action_taken: str
    action_date: str
    deadline_date: str
    reason_codes: List[str]
    reason_texts: List[str]
    form_type: str
    credit_score_used: Optional[int]
    credit_score_range_low: Optional[int]
    credit_score_range_high: Optional[int]
    credit_score_model_name: Optional[str]
    bureau_name: Optional[str]
    generated_at: str
    delivery_channel: Optional[str] = None
    delivered_at: Optional[str] = None
    delivery_status: str = "PENDING"
