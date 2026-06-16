"""
NLG Decision Summary Generator
================================
Auto-generates plain-language underwriting decision narratives suitable for:
  - Loan officer dashboards (professional tone, 3–5 sentences)
  - Applicant-facing portals (8th-grade reading level)
  - Adverse action notices (Reg B / ECOA compliant)

Public API
----------
>>> from explainability.nlg_summarizer import generate_decision_summary, NLGSummary
>>> summary = generate_decision_summary(explanation, decision="REJECT", ...)
>>> print(summary.applicant_narrative)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ECOA / Reg B reason-code mapping
# ---------------------------------------------------------------------------

ECOA_REASON_CODES: Dict[str, str] = {
    "fico_score":        "Credit score below threshold (code 01)",
    "credit_score":      "Credit score below threshold (code 01)",
    "delinquency_count": "Delinquent past or present credit obligations (code 03)",
    "delinquency":       "Delinquent past or present credit obligations (code 03)",
    "debt_to_income":    "Debt-to-income ratio too high (code 08)",
    "dti":               "Debt-to-income ratio too high (code 08)",
    "credit_util":       "Proportion of revolving balances too high (code 10)",
    "utilization":       "Proportion of revolving balances too high (code 10)",
    "avg_utilization_12m": "Proportion of revolving balances too high (code 10)",
    "public_records":    "Number of derogatory public records (code 12)",
    "months_on_book":    "Insufficient credit history length (code 14)",
    "credit_age":        "Insufficient credit history length (code 14)",
    "other":             "Other: {feature_name}",
}

_REG_B_BOILERPLATE = (
    "The federal Equal Credit Opportunity Act prohibits creditors from "
    "discriminating against credit applicants on the basis of race, color, "
    "religion, national origin, sex, marital status, age, or because you "
    "receive public assistance. The federal agency that administers compliance "
    "with this law concerning this creditor is the Consumer Financial "
    "Protection Bureau (CFPB), 1700 G Street NW, Washington, DC 20552."
)


# ---------------------------------------------------------------------------
# NLGSummary dataclass
# ---------------------------------------------------------------------------

@dataclass
class NLGSummary:
    """Output of the NLG summary generation for one underwriting decision.

    Attributes
    ----------
    loan_officer_narrative:
        3–5 sentence professional-tone summary for the loan officer dashboard.
    applicant_narrative:
        Plain-language summary written at an 8th-grade reading level.
    adverse_action_body:
        Reg B–compliant notice body. Empty string when decision is APPROVE.
    top_reasons:
        Up to 4 human-readable ECOA reason strings for adverse action codes.
    model_version:
        Version identifier of the model that produced the prediction.
    generated_at:
        ISO-8601 UTC timestamp of when this summary was generated.
    """
    loan_officer_narrative: str
    applicant_narrative: str
    adverse_action_body: str
    top_reasons: List[str]
    model_version: str
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# ECOA reason-code mapper
# ---------------------------------------------------------------------------

def map_factors_to_ecoa_codes(negative_factors: List[Dict[str, Any]]) -> List[str]:
    """Map the top negative SHAP factors to ECOA adverse action reason strings.

    Parameters
    ----------
    negative_factors:
        ``ExplanationResult.top_negative_factors`` — list of dicts with at
        minimum a ``"feature"`` key.

    Returns
    -------
    list[str]
        Up to 4 ECOA reason strings.
    """
    codes: List[str] = []
    for factor in negative_factors[:4]:
        feature = str(factor.get("feature", "")).lower().replace(" ", "_")
        if feature in ECOA_REASON_CODES:
            code = ECOA_REASON_CODES[feature]
        else:
            # Partial-match fallback
            matched = next(
                (v for k, v in ECOA_REASON_CODES.items() if k != "other" and k in feature),
                None,
            )
            if matched:
                code = matched
            else:
                template = ECOA_REASON_CODES["other"]
                code = template.format(feature_name=feature)
        if code not in codes:
            codes.append(code)
    return codes[:4]


# ---------------------------------------------------------------------------
# Template fallback (no OpenAI required)
# ---------------------------------------------------------------------------

def _template_summary(
    explanation: Any,
    decision: str,
    application_id: str,
    applicant_name: str,
    model_version: str,
    creditor_name: str,
    creditor_phone: str,
) -> NLGSummary:
    """Produce all narrative strings using only f-strings and ExplanationResult data.

    This function must always succeed — it has no external dependencies.

    Parameters
    ----------
    explanation:
        An ``ExplanationResult`` instance.
    decision:
        One of ``"APPROVE"``, ``"REJECT"``, ``"MANUAL_REVIEW"``.
    application_id:
        Unique application identifier.
    applicant_name:
        The applicant's name (default ``"Applicant"``).
    model_version:
        Model version string.
    creditor_name:
        Creditor name for the adverse action notice.
    creditor_phone:
        Creditor phone number for the adverse action notice.

    Returns
    -------
    NLGSummary
    """
    pd_pct = f"{float(explanation.predicted_value) * 100:.1f}%"

    pos = [f["feature"] for f in (explanation.top_positive_factors or [])[:3]]
    neg = [f["feature"] for f in (explanation.top_negative_factors or [])[:3]]

    pos_str = ", ".join(pos) if pos else "overall profile"
    neg_str = ", ".join(neg) if neg else "identified risk factors"

    decision_word = {
        "APPROVE": "approved",
        "REJECT": "declined",
        "MANUAL_REVIEW": "referred for manual review",
    }.get(decision.upper(), decision.lower())

    # Loan officer narrative
    lo_narrative = (
        f"Application {application_id} has been {decision_word} by the automated "
        f"underwriting model (version {model_version}). "
        f"The estimated probability of default is {pd_pct}. "
        f"Positive credit factors include: {pos_str}. "
        f"Key risk factors flagged: {neg_str}. "
        f"Please review the full explanation panel before finalising the decision."
    )

    # Applicant narrative
    if decision.upper() == "APPROVE":
        app_narrative = (
            f"Congratulations, {applicant_name}! Your application has been approved. "
            f"Your strong credit factors, including {pos_str}, supported this decision. "
            f"A representative will contact you with next steps."
        )
    elif decision.upper() == "REJECT":
        app_narrative = (
            f"Dear {applicant_name}, after reviewing your application we are unable "
            f"to approve your request at this time. "
            f"The main reasons relate to: {neg_str}. "
            f"You have the right to know why your application was denied — please see "
            f"the adverse action notice below or contact us for details."
        )
    else:
        app_narrative = (
            f"Dear {applicant_name}, your application is currently under additional "
            f"review by our team. "
            f"We will contact you within 2–3 business days with a decision. "
            f"If you have questions, please call us at {creditor_phone}."
        )

    # Adverse action body (only for REJECT / MANUAL_REVIEW)
    ecoa_codes = map_factors_to_ecoa_codes(explanation.top_negative_factors or [])

    if decision.upper() in {"REJECT", "MANUAL_REVIEW"}:
        reasons_text = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(ecoa_codes)) or "  1. See details above."
        aa_body = (
            f"NOTICE OF ADVERSE ACTION\n\n"
            f"Creditor: {creditor_name}\n"
            f"Phone: {creditor_phone}\n\n"
            f"We regret to inform you that your application has been {decision_word}.\n\n"
            f"Principal reasons for the action:\n"
            f"{reasons_text}\n\n"
            f"{_REG_B_BOILERPLATE}"
        )
    else:
        aa_body = ""

    return NLGSummary(
        loan_officer_narrative=lo_narrative,
        applicant_narrative=app_narrative,
        adverse_action_body=aa_body,
        top_reasons=ecoa_codes,
        model_version=model_version,
    )


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def generate_decision_summary(
    explanation: Any,
    decision: str,
    application_id: str,
    applicant_name: str = "Applicant",
    model_version: str = "unknown",
    creditor_name: str = "Creditor",
    creditor_phone: str = "1-800-000-0000",
    llm_client=None,
    llm_model: str = "gpt-4o-mini",
    timeout: float = 15.0,
) -> NLGSummary:
    """Generate a plain-language underwriting decision narrative.

    Attempts to use an OpenAI LLM to produce polished narratives. Falls back
    gracefully to a template-based approach if OpenAI is unavailable, the API
    key is missing, or any network error occurs.

    Parameters
    ----------
    explanation:
        ``ExplanationResult`` from ``explainability.shap_explainer``.
    decision:
        One of ``"APPROVE"``, ``"REJECT"``, ``"MANUAL_REVIEW"``.
    application_id:
        Unique application identifier.
    applicant_name:
        Name to address in the applicant-facing narrative (default ``"Applicant"``).
    model_version:
        Model version string (included in narratives and the summary record).
    creditor_name:
        Creditor name for Reg B adverse action notice.
    creditor_phone:
        Creditor contact phone for adverse action notice.
    llm_client:
        Optional pre-built ``openai.OpenAI`` instance. If None, the function
        attempts to create one from the environment.
    llm_model:
        OpenAI model identifier (default ``"gpt-4o-mini"``).
    timeout:
        Request timeout in seconds for the LLM call.

    Returns
    -------
    NLGSummary
        Always returns a populated ``NLGSummary``. Never raises.
    """
    pd_pct = f"{float(explanation.predicted_value) * 100:.1f}%"
    pos_factors = explanation.top_positive_factors or []
    neg_factors = explanation.top_negative_factors or []

    # ── Attempt LLM path ───────────────────────────────────────────────────
    if llm_client is None:
        try:
            import openai  # noqa: PLC0415
            api_key = os.getenv("OPENAI_API_KEY", "")
            if not api_key:
                raise EnvironmentError("OPENAI_API_KEY not set")
            llm_client = openai.OpenAI(api_key=api_key)
        except (ImportError, EnvironmentError) as exc:
            logger.warning(
                "NLG: OpenAI unavailable (%s). Using template fallback.", exc
            )
            return _template_summary(
                explanation, decision, application_id,
                applicant_name, model_version, creditor_name, creditor_phone,
            )

    try:
        pos_text = "; ".join(
            f"{f['feature']} (SHAP {f['shap_value']:+.4f})" for f in pos_factors[:3]
        ) or "none identified"
        neg_text = "; ".join(
            f"{f['feature']} (SHAP {f['shap_value']:+.4f})" for f in neg_factors[:3]
        ) or "none identified"

        # ── Loan-officer narrative ─────────────────────────────────────────
        lo_prompt = (
            f"You are a credit risk analyst writing a 3–5 sentence professional summary "
            f"of an automated underwriting decision for a loan officer dashboard.\n\n"
            f"Application ID: {application_id}\n"
            f"Decision: {decision}\n"
            f"Estimated probability of default: {pd_pct}\n"
            f"Model version: {model_version}\n"
            f"Top positive credit factors: {pos_text}\n"
            f"Top risk factors: {neg_text}\n\n"
            f"Write a concise (max 200 words) professional-tone summary."
        )

        # ── Applicant-facing narrative ─────────────────────────────────────
        app_prompt = (
            f"You are helping to write a plain-language explanation for a credit applicant "
            f"(8th-grade reading level). Write 2–3 clear sentences.\n\n"
            f"Decision: {decision}\n"
            f"Applicant name: {applicant_name}\n"
            f"Top favourable factors: {pos_text}\n"
            f"Top risk factors: {neg_text}\n\n"
            f"Keep the tone respectful and empathetic (max 100 words)."
        )

        lo_response = llm_client.chat.completions.create(
            model=llm_model,
            messages=[{"role": "user", "content": lo_prompt}],
            max_tokens=300,
            timeout=timeout,
        )
        lo_narrative = lo_response.choices[0].message.content.strip()

        app_response = llm_client.chat.completions.create(
            model=llm_model,
            messages=[{"role": "user", "content": app_prompt}],
            max_tokens=150,
            timeout=timeout,
        )
        app_narrative = app_response.choices[0].message.content.strip()

    except Exception as exc:
        logger.warning(
            "NLG: LLM call failed (%s). Using template fallback.", exc
        )
        return _template_summary(
            explanation, decision, application_id,
            applicant_name, model_version, creditor_name, creditor_phone,
        )

    # ── Adverse action body ────────────────────────────────────────────────
    ecoa_codes = map_factors_to_ecoa_codes(neg_factors)
    if decision.upper() in {"REJECT", "MANUAL_REVIEW"}:
        reasons_text = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(ecoa_codes)) or "  1. See details above."
        aa_body = (
            f"NOTICE OF ADVERSE ACTION\n\n"
            f"Creditor: {creditor_name}\n"
            f"Phone: {creditor_phone}\n\n"
            f"We regret to inform you that your application has been declined.\n\n"
            f"Principal reasons for the action:\n"
            f"{reasons_text}\n\n"
            f"{_REG_B_BOILERPLATE}"
        )
    else:
        aa_body = ""

    return NLGSummary(
        loan_officer_narrative=lo_narrative,
        applicant_narrative=app_narrative,
        adverse_action_body=aa_body,
        top_reasons=ecoa_codes,
        model_version=model_version,
    )


# ---------------------------------------------------------------------------
# __main__ demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from explainability.shap_explainer import ExplanationResult

    # Minimal synthetic ExplanationResult
    sample_result = ExplanationResult(
        top_positive_factors=[
            {"feature": "fico_score",     "shap_value": -0.12, "direction": "positive"},
            {"feature": "months_on_book", "shap_value": -0.08, "direction": "positive"},
        ],
        top_negative_factors=[
            {"feature": "debt_to_income",    "shap_value": 0.18, "direction": "negative"},
            {"feature": "delinquency_count", "shap_value": 0.14, "direction": "negative"},
            {"feature": "credit_util",       "shap_value": 0.09, "direction": "negative"},
        ],
        predicted_value=0.23,
        explanation_text="Sample explanation.",
    )

    summary = generate_decision_summary(
        explanation=sample_result,
        decision="REJECT",
        application_id="APP-DEMO-001",
        applicant_name="Jane Smith",
        model_version="v1.2.0",
        creditor_name="Demo Bank",
        creditor_phone="1-800-555-1234",
    )

    print("=== Loan Officer Narrative ===")
    print(summary.loan_officer_narrative)
    print("\n=== Applicant Narrative ===")
    print(summary.applicant_narrative)
    print("\n=== Adverse Action Body ===")
    print(summary.adverse_action_body)
    print("\n=== Top ECOA Reason Codes ===")
    for r in summary.top_reasons:
        print(" -", r)
