"""
compliance/adverse_action_generator.py
=======================================
Generates AdverseActionNotice objects and renders CFPB Model Form C-1 text.

Public API
----------
>>> from compliance.adverse_action_generator import (
...     generate_notice,
...     render_c1_text,
...     notice_to_dict,
... )
"""
from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from compliance.adverse_action import (
    REG_B_REASON_CODES,
    AdverseActionNotice,
    map_shap_factors_to_reg_b_codes,
    select_form_type,
)


# ---------------------------------------------------------------------------
# Notice generator
# ---------------------------------------------------------------------------


def generate_notice(
    application_id: str,
    tenant_id: str,
    decision_result: Any,
    explanation_result: Any,
    tenant_config: Dict[str, Any],
) -> AdverseActionNotice:
    """Build an AdverseActionNotice for a REJECT decision.

    Parameters
    ----------
    application_id:
        UUID of the declined application.
    tenant_id:
        Tenant identifier.
    decision_result:
        A ``DecisionResult`` dataclass or plain dict.  Must have
        ``decision == "REJECT"`` — raises ``ValueError`` otherwise.
        Also reads ``reason_codes`` (list of strings).
    explanation_result:
        ``ExplanationResult`` from ``explainability.shap_explainer`` or
        ``None``.  When provided, SHAP-derived codes are merged in.
    tenant_config:
        Tenant configuration dict.  Expected keys:
        ``creditor_name``, ``applicant_name`` (optional),
        ``bureau_config`` (dict with ``credit_score_model_name``,
        ``bureau_name``).

    Returns
    -------
    AdverseActionNotice

    Raises
    ------
    ValueError
        If the decision is not ``"REJECT"``.
    """
    # Normalise decision_result
    if isinstance(decision_result, dict):
        decision  = decision_result.get("decision", "")
        dr_reason_codes: List[str] = decision_result.get("reason_codes", [])
        credit_score_used: Optional[int] = decision_result.get("credit_score_used")
    else:
        decision  = getattr(decision_result, "decision", "")
        dr_reason_codes = list(getattr(decision_result, "reason_codes", []))
        credit_score_used = getattr(decision_result, "credit_score_used", None)

    if decision != "REJECT":
        raise ValueError(
            f"decision must be REJECT to generate adverse action notice; got {decision!r}"
        )

    # Merge reason codes from decision_result and SHAP explanation
    combined_codes: List[str] = list(dr_reason_codes)

    if explanation_result is not None:
        try:
            # Lazy import to avoid circular imports
            from explainability.shap_explainer import ExplanationResult  # noqa: F401
        except ImportError:
            pass
        try:
            top_neg = (
                explanation_result.top_negative_factors
                if hasattr(explanation_result, "top_negative_factors")
                else explanation_result.get("top_negative_factors", [])
            )
            shap_codes = map_shap_factors_to_reg_b_codes(top_neg)
            for code in shap_codes:
                if code not in combined_codes:
                    combined_codes.append(code)
        except Exception:
            pass

    # Deduplicate and truncate to 4, keeping only known codes
    seen: set[str] = set()
    final_codes: List[str] = []
    for code in combined_codes:
        if code not in seen:
            seen.add(code)
            final_codes.append(code)
        if len(final_codes) >= 4:
            break

    # Ensure at least 1 code
    if not final_codes:
        final_codes = ["AA01"]

    reason_texts = [REG_B_REASON_CODES.get(c, c) for c in final_codes]

    # Dates
    today = date.today()
    action_dt = today.isoformat()
    deadline_dt = (today + timedelta(days=30)).isoformat()

    # Tenant config
    creditor_name = tenant_config.get("creditor_name", "The Creditor")
    applicant_name = tenant_config.get("applicant_name", "The Applicant")
    bureau_cfg = tenant_config.get("bureau_config", {})
    score_model = bureau_cfg.get("credit_score_model_name") if bureau_cfg else None
    bureau_name = bureau_cfg.get("bureau_name") if bureau_cfg else None

    # Credit score info
    score_low: Optional[int] = bureau_cfg.get("credit_score_range_low", 300) if bureau_cfg else 300
    score_high: Optional[int] = bureau_cfg.get("credit_score_range_high", 850) if bureau_cfg else 850

    generated_at = datetime.now(timezone.utc).isoformat()

    return AdverseActionNotice(
        notice_id=str(uuid.uuid4()),
        application_id=str(application_id),
        tenant_id=str(tenant_id),
        applicant_name=str(applicant_name),
        creditor_name=str(creditor_name),
        action_taken="Application Denied",
        action_date=action_dt,
        deadline_date=deadline_dt,
        reason_codes=final_codes,
        reason_texts=reason_texts,
        form_type=select_form_type("denial"),
        credit_score_used=int(credit_score_used) if credit_score_used is not None else None,
        credit_score_range_low=int(score_low) if score_low is not None else None,
        credit_score_range_high=int(score_high) if score_high is not None else None,
        credit_score_model_name=score_model,
        bureau_name=bureau_name,
        generated_at=generated_at,
    )


# ---------------------------------------------------------------------------
# Plain-text renderer — CFPB Model Form C-1
# ---------------------------------------------------------------------------


def render_c1_text(notice: AdverseActionNotice) -> str:
    """Render *notice* as plain text following CFPB Model Form C-1 structure.

    Output is deterministic (no timestamps in body).

    Returns
    -------
    str
    """
    lines: List[str] = [
        "NOTICE OF ACTION TAKEN AND STATEMENT OF REASONS",
        "",
        f"Creditor: {notice.creditor_name}",
        f"Date: {notice.action_date}",
        f"Applicant: {notice.applicant_name}",
        f"Application ID: {notice.application_id}",
        "",
        "DESCRIPTION OF ACTION TAKEN:",
        notice.action_taken,
        "",
        "STATEMENT OF REASONS:",
    ]

    for i, text in enumerate(notice.reason_texts, start=1):
        lines.append(f"{i}. {text}")

    lines.append("")

    # Conditional credit score disclosure block
    if notice.credit_score_used is not None:
        lines += [
            "DISCLOSURE OF USE OF INFORMATION FROM AN OUTSIDE SOURCE:",
            "Our credit decision was based in whole or in part on information obtained",
            "from a consumer reporting agency. The agency that provided the information",
            f"is: {notice.bureau_name}. The credit score used in making this credit decision was",
            f"{notice.credit_score_used}. Scores range from a low of {notice.credit_score_range_low} to",
            f"a high of {notice.credit_score_range_high} under the scoring model: {notice.credit_score_model_name}.",
            "",
        ]

    lines += [
        "You have a right to obtain a free copy of your consumer report from the",
        "consumer reporting agency listed above for a period of 60 days from the date",
        "of this notice. If you find information in your report that you believe is",
        "inaccurate or incomplete, you have the right to dispute the matter with the",
        "reporting agency.",
        "",
        "You have a right to know whether information in your file at a consumer",
        "reporting agency was used in connection with any credit transaction initiated",
        "or reviewed by you. You may contact the consumer reporting agency at any time",
        "to see your file and to have any inaccurate information corrected.",
        "",
        f"Please contact {notice.creditor_name} if you have questions about this notice.",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def notice_to_dict(notice: AdverseActionNotice) -> Dict[str, Any]:
    """Return a JSON-serialisable dict for audit log storage."""
    return dataclasses.asdict(notice)


def generate_conditional_approval_notice(
    application_id: str,
    applicant_name: str,
    creditor_name: str,
    conditional_approval: Any,
) -> str:
    """Generate a conditional approval letter using Jinja2 template."""
    import jinja2
    from pathlib import Path

    _template_dir = Path(__file__).parent / "templates"
    _jinja_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(_template_dir),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Get conditions based on type
    if isinstance(conditional_approval, dict):
        conds = conditional_approval.get("conditions", [])
        deadline = conditional_approval.get("condition_deadline_days", 30)
    else:
        conds = getattr(conditional_approval, "conditions", [])
        deadline = getattr(conditional_approval, "condition_deadline_days", 30)

    template = _jinja_env.get_template("conditional_approval.j2")
    return template.render(
        action_date=date.today().isoformat(),
        creditor_name=creditor_name,
        applicant_name=applicant_name,
        application_id=application_id,
        deadline_days=deadline,
        conditions=conds
    )
