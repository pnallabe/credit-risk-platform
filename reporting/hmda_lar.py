"""HMDA LAR (Loan/Application Register) export.

Implements a minimal HMDA FIG 2023-aligned pipe-delimited exporter.
This module is intentionally "data transformation only": it accepts audit-log
records (dicts) and produces `HMDALARRecord` rows.

Where fields cannot be mapped from the audit log, we use the HMDA exempt coding
specified in the implementation plan:
- numeric exempt value: 1111
- string exempt value: "Exempt"

Important: This is not a full FIG implementation. It is a pragmatic extract
builder for governance/audit needs and should be extended with your institution's
authoritative HMDA mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HMDA_EXEMPT_NUMERIC = 1111
HMDA_EXEMPT_STRING = "Exempt"

# A minimal, documented mapping from common (institution-specific) adverse action
# reason codes to HMDA FIG denial reason codes.
#
# HMDA FIG (2023) denial reason codes (partial):
#   1=Debt-to-income ratio, 2=Employment history, 3=Credit history,
#   4=Collateral, 5=Insufficient cash, 6=Unverifiable information,
#   7=Credit application incomplete, 8=Mortgage insurance denied, 9=Other
FCRA_TO_HMDA_DENIAL_REASON_1: Dict[str, int] = {
    "CREDIT_HISTORY": 3,
    "FCRA_CREDIT_HISTORY": 3,
    "DTI": 1,
    "DEBT_TO_INCOME": 1,
    "EMPLOYMENT": 2,
    "INCOMPLETE": 7,
    "MORTGAGE_INSURANCE": 8,
    "OTHER": 9,
}


@dataclass(frozen=True)
class HMDALARRecord:
    lei: str
    lar_id: str
    application_date: str
    loan_type: int
    loan_purpose: int
    preapproval: int
    construction_method: int
    occupancy_type: int
    loan_amount: float
    action_taken: int
    action_taken_date: str
    state_code: str
    county_code: str
    census_tract: str
    applicant_ethnicity_1: int
    co_applicant_ethnicity_1: int
    applicant_race_1: int
    co_applicant_race_1: int
    applicant_sex: int
    co_applicant_sex: int
    applicant_age: int
    co_applicant_age: int
    income: int
    purchaser_type: int
    rate_spread: float | None
    hoepa_status: int
    lien_status: int
    credit_score_applicant: int
    credit_score_model_applicant: int
    denial_reason_1: int | None
    total_loan_costs: float | None
    interest_rate: float
    total_points_fees: float | None
    debt_to_income_ratio: str
    combined_loan_to_value: float | None
    loan_term: int
    introductory_rate_period: int | None
    balloon_payment: int
    interest_only_payment: int
    negative_amortization: int
    other_non_amortizing_features: int
    property_value: float | None
    manufactured_home_secured_property_type: int
    manufactured_home_land_property_interest: int
    total_units: int
    multifamily_affordable_units: str
    submission_of_application: int
    initially_payable_to_institution: int
    aus_1: int
    reverse_mortgage: int
    open_end_line_of_credit: int
    business_or_commercial_purpose: int


def _to_yyyymmdd(val: Any) -> str:
    if val is None or val == "":
        return HMDA_EXEMPT_STRING

    if isinstance(val, datetime):
        return val.strftime("%Y%m%d")

    s = str(val).strip()
    # Common formats: YYYY-MM-DD, YYYYMMDD, ISO timestamp
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[0:4] + s[5:7] + s[8:10]
    if len(s) >= 8 and s[:8].isdigit():
        return s[:8]

    # Fallback: exempt
    return HMDA_EXEMPT_STRING


def _estimate_credit_score_from_pd_score(pd_score: Any) -> int:
    """Approximate inverse score mapping.

    HMDA needs a credit score value; audit logs may store a PD score instead.
    We apply a simple monotone transform (higher PD -> lower credit score).

    This is an assumption and should be replaced with an institution-specific
    scorecard inversion.
    """

    try:
        p = float(pd_score)
    except Exception:
        return HMDA_EXEMPT_NUMERIC

    p = max(0.0, min(1.0, p))
    # Map PD in [0,1] roughly onto [850,300]
    score = int(round(850 - p * 550))
    return int(max(300, min(850, score)))


def _map_denial_reason(reasons: Any) -> int:
    if reasons is None:
        return HMDA_EXEMPT_NUMERIC

    if isinstance(reasons, str):
        code = reasons.strip().upper()
        return int(FCRA_TO_HMDA_DENIAL_REASON_1.get(code, HMDA_EXEMPT_NUMERIC))

    if isinstance(reasons, list) and reasons:
        first = str(reasons[0]).strip().upper()
        return int(FCRA_TO_HMDA_DENIAL_REASON_1.get(first, HMDA_EXEMPT_NUMERIC))

    return HMDA_EXEMPT_NUMERIC


def build_lar_from_audit_log(
    audit_records: List[dict],
    lei: str,
    product_filter: Optional[List[str]] = None,
) -> List[HMDALARRecord]:
    """Map audit log records to HMDA FIG 2023 LAR records.

    Included products are restricted to {"mortgage", "home_equity"} unless
    `product_filter` is provided.

    Mapping assumptions are documented inline; unmappable fields use HMDA exempt
    values (1111 / "Exempt").
    """

    allowed = {"mortgage", "home_equity"}
    if product_filter is not None:
        allowed = {str(x).lower().strip() for x in product_filter}

    out: List[HMDALARRecord] = []

    for i, rec in enumerate(audit_records):
        product = str(rec.get("product", "")).lower().strip()
        if product not in allowed:
            continue

        features = rec.get("features") or {}
        if not isinstance(features, dict):
            features = {}

        application_id = str(rec.get("application_id") or rec.get("id") or f"lar_{i}")

        decision = str(rec.get("decision") or rec.get("action") or "").upper().strip()
        if decision in {"APPROVE", "APPROVED"}:
            action_taken = 2  # Approved-NotAccepted (originated vs accepted not known)
        elif decision in {"DENY", "DENIED", "REJECT", "REJECTED"}:
            action_taken = 3
        elif decision in {"WITHDRAW", "WITHDRAWN"}:
            action_taken = 4
        elif decision in {"CLOSED", "INCOMPLETE"}:
            action_taken = 5
        else:
            action_taken = 4

        application_date = _to_yyyymmdd(rec.get("application_date") or rec.get("event_time"))
        action_taken_date = _to_yyyymmdd(rec.get("action_taken_date") or rec.get("decision_date") or rec.get("event_time"))

        # Loan amount: prefer explicit amount, else feature field, else exempt.
        loan_amount = rec.get("loan_amount")
        if loan_amount is None:
            loan_amount = features.get("loan_amount") or features.get("requested_amount")
        try:
            loan_amount_f = float(loan_amount) if loan_amount is not None else float(HMDA_EXEMPT_NUMERIC)
        except Exception:
            loan_amount_f = float(HMDA_EXEMPT_NUMERIC)

        # Income in thousands. If annual_income appears to be dollars, convert.
        income_val = features.get("annual_income") or rec.get("income")
        try:
            inc = float(income_val)
            income_thousands = int(round(inc / 1000.0)) if inc > 1000 else int(round(inc))
        except Exception:
            income_thousands = HMDA_EXEMPT_NUMERIC

        dti = features.get("dti") or rec.get("dti")
        if dti is None:
            dti_str = HMDA_EXEMPT_STRING
        else:
            try:
                dti_str = str(round(float(dti), 4))
            except Exception:
                dti_str = HMDA_EXEMPT_STRING

        ltv = features.get("ltv") or features.get("combined_loan_to_value")
        try:
            combined_ltv = float(ltv) if ltv is not None else float(HMDA_EXEMPT_NUMERIC)
        except Exception:
            combined_ltv = float(HMDA_EXEMPT_NUMERIC)

        census_tract = features.get("census_tract") or rec.get("census_tract")
        census_tract_str = HMDA_EXEMPT_STRING if not census_tract else str(census_tract)

        state_code = str(features.get("state") or rec.get("state") or HMDA_EXEMPT_STRING)
        county_code = str(features.get("county") or rec.get("county") or HMDA_EXEMPT_STRING)

        pd_score = rec.get("pd_score")
        if pd_score is None:
            pd_score = rec.get("pd") or features.get("pd_score")

        credit_score = _estimate_credit_score_from_pd_score(pd_score)

        denial_reason_1 = _map_denial_reason(rec.get("adverse_action_reasons"))

        # interest_rate: use apr_assigned if present (assumption)
        ir = rec.get("apr_assigned") or rec.get("interest_rate")
        try:
            interest_rate = float(ir) if ir is not None else 0.0
        except Exception:
            interest_rate = 0.0

        out.append(
            HMDALARRecord(
                lei=str(lei),
                lar_id=application_id,
                application_date=application_date,
                loan_type=int(rec.get("loan_type") or 1),
                loan_purpose=int(rec.get("loan_purpose") or 1),
                preapproval=int(rec.get("preapproval") or 1),
                construction_method=int(rec.get("construction_method") or 1),
                occupancy_type=int(rec.get("occupancy_type") or 1),
                loan_amount=float(loan_amount_f),
                action_taken=int(action_taken),
                action_taken_date=action_taken_date,
                state_code=state_code,
                county_code=county_code,
                census_tract=census_tract_str,
                applicant_ethnicity_1=int(rec.get("applicant_ethnicity_1") or HMDA_EXEMPT_NUMERIC),
                co_applicant_ethnicity_1=int(rec.get("co_applicant_ethnicity_1") or HMDA_EXEMPT_NUMERIC),
                applicant_race_1=int(rec.get("applicant_race_1") or HMDA_EXEMPT_NUMERIC),
                co_applicant_race_1=int(rec.get("co_applicant_race_1") or HMDA_EXEMPT_NUMERIC),
                applicant_sex=int(rec.get("applicant_sex") or HMDA_EXEMPT_NUMERIC),
                co_applicant_sex=int(rec.get("co_applicant_sex") or HMDA_EXEMPT_NUMERIC),
                applicant_age=int(rec.get("applicant_age") or HMDA_EXEMPT_NUMERIC),
                co_applicant_age=int(rec.get("co_applicant_age") or HMDA_EXEMPT_NUMERIC),
                income=int(income_thousands),
                purchaser_type=int(rec.get("purchaser_type") or HMDA_EXEMPT_NUMERIC),
                rate_spread=float(rec.get("rate_spread") or HMDA_EXEMPT_NUMERIC),
                hoepa_status=int(rec.get("hoepa_status") or 2),
                lien_status=int(rec.get("lien_status") or 1),
                credit_score_applicant=int(credit_score),
                credit_score_model_applicant=int(rec.get("credit_score_model_applicant") or HMDA_EXEMPT_NUMERIC),
                denial_reason_1=int(denial_reason_1),
                total_loan_costs=float(rec.get("total_loan_costs") or HMDA_EXEMPT_NUMERIC),
                interest_rate=float(interest_rate),
                total_points_fees=float(rec.get("total_points_fees") or HMDA_EXEMPT_NUMERIC),
                debt_to_income_ratio=str(dti_str),
                combined_loan_to_value=float(combined_ltv),
                loan_term=int(rec.get("loan_term") or HMDA_EXEMPT_NUMERIC),
                introductory_rate_period=int(rec.get("introductory_rate_period") or HMDA_EXEMPT_NUMERIC),
                balloon_payment=int(rec.get("balloon_payment") or 2),
                interest_only_payment=int(rec.get("interest_only_payment") or 2),
                negative_amortization=int(rec.get("negative_amortization") or 2),
                other_non_amortizing_features=int(rec.get("other_non_amortizing_features") or 2),
                property_value=float(rec.get("property_value") or HMDA_EXEMPT_NUMERIC),
                manufactured_home_secured_property_type=int(rec.get("manufactured_home_secured_property_type") or HMDA_EXEMPT_NUMERIC),
                manufactured_home_land_property_interest=int(rec.get("manufactured_home_land_property_interest") or HMDA_EXEMPT_NUMERIC),
                total_units=int(rec.get("total_units") or 1),
                multifamily_affordable_units=str(rec.get("multifamily_affordable_units") or HMDA_EXEMPT_STRING),
                submission_of_application=int(rec.get("submission_of_application") or HMDA_EXEMPT_NUMERIC),
                initially_payable_to_institution=int(rec.get("initially_payable_to_institution") or 1),
                aus_1=int(rec.get("aus_1") or HMDA_EXEMPT_NUMERIC),
                reverse_mortgage=int(rec.get("reverse_mortgage") or 2),
                open_end_line_of_credit=int(rec.get("open_end_line_of_credit") or 2),
                business_or_commercial_purpose=int(rec.get("business_or_commercial_purpose") or 2),
            )
        )

    return out


def export_lar_pipe_delimited(records: List[HMDALARRecord], output_path: Path) -> int:
    """Write HMDA pipe-delimited file. No header row."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    for r in records:
        parts: List[str] = []
        for f in fields(HMDALARRecord):
            val = getattr(r, f.name)
            if val is None:
                # To satisfy the prompt constraint, we prefer exempt codes upstream.
                val = ""  # keep exporter permissive
            parts.append(str(val))
        lines.append("|".join(parts))

    output_path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def validate_lar(records: List[HMDALARRecord]) -> List[dict]:
    """Run basic validity checks and return a list of errors."""

    errors: List[dict] = []

    for r in records:
        if len(str(r.lei)) != 20:
            errors.append({"lar_id": r.lar_id, "field": "lei", "error": "LEI must be 20 characters"})

        if not (1 <= int(r.action_taken) <= 8):
            errors.append({"lar_id": r.lar_id, "field": "action_taken", "error": "action_taken must be in 1–8"})

        tract = str(r.census_tract)
        if tract != HMDA_EXEMPT_STRING:
            if not (len(tract) == 11 and tract.isdigit()):
                errors.append({"lar_id": r.lar_id, "field": "census_tract", "error": "census_tract must be 11 digits or 'Exempt'"})

        try:
            if float(r.loan_amount) <= 0:
                errors.append({"lar_id": r.lar_id, "field": "loan_amount", "error": "loan_amount must be > 0"})
        except Exception:
            errors.append({"lar_id": r.lar_id, "field": "loan_amount", "error": "loan_amount must be numeric"})

    return errors
