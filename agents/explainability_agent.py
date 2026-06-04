"""
Explainability & Compliance Agent
===================================
Domain Owner : Model Risk Management / Compliance
SR 11-7 Stage: Model transparency + FCRA/ECOA compliance

Responsibilities
----------------
* Generate SHAP-based per-prediction explanations
* Produce FCRA-compliant adverse action notices
* Map SHAP top-factors → human-readable reason codes
* Support ECOA/Reg-B disclosure text generation
* Optionally generate LIME explanations for non-tree models

Inputs  : model scores, decisions, feature vectors, loaded model objects
Outputs : AgentResult.payload["explanations"] = List[ExplanationRecord]
          AgentResult.payload["adverse_action_notices"] = List[dict]
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from agents.base import AgentResult, AgentStatus, BaseAgent
from schemas.contracts import CreditDecision, DecisionLabel, ExplanationRecord, ModelScores

logger = logging.getLogger(__name__)

try:
    from explainability.shap_explainer import explain_prediction
    _SHAP_AVAILABLE = True
except ImportError:
    _SHAP_AVAILABLE = False
    logger.warning("SHAP explainer not importable — ExplainabilityAgent in stub mode")


# ---------------------------------------------------------------------------
# Human-readable feature label map
# ---------------------------------------------------------------------------

_FEATURE_LABELS: Dict[str, str] = {
    "credit_utilization":       "Credit Utilization Ratio",
    "income_stability_score":   "Income Stability Score",
    "repayment_capacity":       "Repayment Capacity",
    "debt_service_coverage":    "Debt Service Coverage",
    "credit_age_score":         "Credit History Length",
    "derogatory_penalty":       "Derogatory Marks",
    "months_since_delinquency": "Months Since Last Delinquency",
    "log_loan_amount":          "Requested Loan Amount",
    "log_annual_income":        "Annual Income",
    "dti_x_loan_amount":        "Debt-to-Income × Loan Amount",
    "employment_encoded":       "Employment Status",
    "thin_file_alt_score":      "Alternative Data Score (Thin-File)",
}

# FCRA reason code descriptions
_REASON_CODE_TEXT: Dict[str, str] = {
    "AA01": "High probability of default based on credit profile",
    "AA02": "Fraud or identity risk indicators detected in your application",
    "AA03": "Insufficient number of open accounts or credit history",
    "AA04": "Debt-to-income ratio exceeds our policy limits",
    "AA05": "Your application has been flagged for manual review",
}


# ---------------------------------------------------------------------------
# Adverse Action Notice Generator
# ---------------------------------------------------------------------------


def build_adverse_action_notice(
    application_id: str,
    decision: DecisionLabel,
    reason_codes: List[str],
    top_factors: List[Dict[str, Any]],
    header_text: str,
) -> str:
    """
    Generates FCRA-compliant adverse action text.
    Suitable for email/letter generation.
    """
    lines = [
        f"ADVERSE ACTION NOTICE",
        f"Application ID: {application_id}",
        f"Decision: {decision.value}",
        "",
        header_text.strip(),
        "",
        "PRIMARY REASON(S) FOR THIS DECISION:",
    ]
    for code in reason_codes:
        desc = _REASON_CODE_TEXT.get(code, code)
        lines.append(f"  [{code}] {desc}")

    if top_factors:
        lines += ["", "KEY FACTORS THAT INFLUENCED THIS DECISION (from highest to lowest impact):"]
        for i, factor in enumerate(top_factors[:5], 1):
            label = _FEATURE_LABELS.get(factor.get("feature", ""), factor.get("feature", ""))
            direction = "+" if factor.get("shap_value", 0) > 0 else "-"
            lines.append(f"  {i}. {label} ({direction}{abs(factor.get('shap_value', 0)):.4f})")

    lines += [
        "",
        "YOUR RIGHTS UNDER THE FAIR CREDIT REPORTING ACT (FCRA):",
        "  - You have the right to obtain a free copy of your credit report within 60 days.",
        "  - You have the right to dispute inaccurate information.",
        "  - Contact the credit bureau listed below for your free report.",
        "",
        "This notice is provided in compliance with the Equal Credit Opportunity Act (ECOA).",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ExplainabilityAgent
# ---------------------------------------------------------------------------


class ExplainabilityAgent(BaseAgent):
    """
    Produces SHAP-based explanations and FCRA adverse action notices.

    Config keys (agent_config.yaml → explainability):
      method, top_n_factors, save_waterfall_plot,
      reason_code_map, adverse_action_header
    """

    name = "ExplainabilityAgent"

    def __init__(
        self,
        config: Dict[str, Any] | None = None,
        model: Any = None,
    ):
        super().__init__(config)
        self._method: str = self.config.get("method", "shap")
        self._top_n: int = self.config.get("top_n_factors", 5)
        self._header: str = self.config.get(
            "adverse_action_header",
            "We regret to inform you that your application has been declined.",
        )
        self._model = model  # Optional: pass pre-loaded model object

    # ------------------------------------------------------------------
    # SHAP explanation stub (when model not available)
    # ------------------------------------------------------------------

    @staticmethod
    def _stub_explain(
        features: Dict[str, float], top_n: int
    ) -> List[Dict[str, Any]]:
        """Synthetic SHAP values sorted by absolute magnitude."""
        items = [(k, v * 0.1) for k, v in list(features.items())[:top_n]]
        return [{"feature": k, "shap_value": v} for k, v in sorted(items, key=lambda x: abs(x[1]), reverse=True)]

    # ------------------------------------------------------------------
    # Core agent logic
    # ------------------------------------------------------------------

    def _run(self, inputs: Dict[str, Any]) -> AgentResult:
        """
        inputs expected keys:
          "model_scores" : List[dict]       — ModelScores dicts
          "decisions"    : List[dict]       — CreditDecision dicts
          "feature_vectors" : List[dict]    — FeatureVector dicts
        """
        score_dicts = inputs.get("model_scores", [])
        decision_dicts = inputs.get("decisions", [])
        fv_dicts = inputs.get("feature_vectors", [])

        if not decision_dicts:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILURE,
                errors=["No decisions provided to ExplainabilityAgent"],
            )

        # Build lookup maps
        dec_map: Dict[str, CreditDecision] = {
            d["application_id"]: CreditDecision(**{**d, "tenant_id": d.get("tenant_id", "default")}) for d in decision_dicts
        }
        score_map: Dict[str, ModelScores] = {
            s["application_id"]: ModelScores(**{**s, "tenant_id": s.get("tenant_id", "default")}) for s in score_dicts
        }
        feat_map: Dict[str, Dict[str, float]] = {
            fv["application_id"]: fv.get("features", {}) for fv in fv_dicts
        }

        explanations: List[ExplanationRecord] = []
        notices: List[Dict[str, Any]] = []

        for app_id, decision in dec_map.items():
            features = feat_map.get(app_id, {})
            score = score_map.get(app_id)

            # Attempt real SHAP explanation
            top_factors: List[Dict[str, Any]] = []
            shap_values: Optional[Dict[str, float]] = None

            if _SHAP_AVAILABLE and self._model is not None and features:
                try:
                    df_row = pd.DataFrame([features])
                    ex_result = explain_prediction(
                        model=self._model,
                        features_row_df=df_row,
                        decision_label=decision.decision.value,
                        top_n=self._top_n,
                    )
                    top_factors = (
                        ex_result.top_positive_factors + ex_result.top_negative_factors
                    )
                    shap_values = {
                        k: float(v)
                        for k, v in zip(ex_result.feature_names or [], ex_result.shap_values or [])
                    }
                except Exception as exc:  # noqa: BLE001
                    self._log.warning("SHAP failed for %s: %s", app_id, exc)
                    top_factors = self._stub_explain(features, self._top_n)
            else:
                top_factors = self._stub_explain(features, self._top_n)

            # Build adverse action notice for reject / review
            notice_text: Optional[str] = None
            if decision.decision in (DecisionLabel.REJECT, DecisionLabel.MANUAL_REVIEW):
                notice_text = build_adverse_action_notice(
                    application_id=app_id,
                    decision=decision.decision,
                    reason_codes=decision.reason_codes,
                    top_factors=top_factors,
                    header_text=self._header,
                )
                notices.append({"application_id": app_id, "notice": notice_text})

            explanations.append(
                ExplanationRecord(
                    application_id=app_id,
                    tenant_id=decision.tenant_id,
                    decision=decision.decision,
                    top_factors=top_factors,
                    adverse_action_text=notice_text,
                    shap_values=shap_values,
                    method=self._method if _SHAP_AVAILABLE and self._model else "stub",
                )
            )

        self._log.info(
            "Generated %d explanations; %d adverse action notices",
            len(explanations),
            len(notices),
        )

        return AgentResult(
            agent_name=self.name,
            status=AgentStatus.SUCCESS,
            payload={
                "explanations": [e.model_dump() for e in explanations],
                "adverse_action_notices": notices,
            },
        )
