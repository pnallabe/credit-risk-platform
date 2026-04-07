"""
Decision Engine Agent
======================
Domain Owner : Credit Risk Policy / Decisioning
SR 11-7 Stage: Production decisioning with full audit trail

Responsibilities
----------------
* Apply hard policy rules (loaded from config — no hardcoding)
* Apply model score-based cutoffs (approve / review / reject)
* Support champion / challenger experiment routing
* Emit FCRA-compliant adverse action codes
* Log every decision to the audit trail (decision_audit.db)

Inputs  : AgentResult.payload["model_scores"]  from RiskModelingAgent
          + original validated records for context (dti, open_accounts, etc.)
Outputs : AgentResult.payload["decisions"] = List[CreditDecision]
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from agents.base import AgentResult, AgentStatus, BaseAgent
from credit_core.policy import evaluate_policy
from decision_engine.policy_dsl import PolicyDSLError, evaluate_rule, validate_rule
from schemas.contracts import CreditDecision, DecisionLabel, FraudFlag, ModelScores

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hard Rule Evaluator (P0.3: eval()-free, DSL-based)
# ---------------------------------------------------------------------------


class HardRule:
    """
    Evaluates a single hard policy rule against a merged context dict using
    the safe ``decision_engine.policy_dsl`` — no ``eval()`` calls.

    The ``condition`` key in the config must follow the DSL schema:
      Leaf:     { field, op, value }
      Compound: { all: [...] } or { any: [...] }

    See ``decision_engine/policy_dsl.py`` for full documentation.
    """

    def __init__(self, rule_cfg: Dict[str, Any]):
        self.rule_id: str = rule_cfg["rule_id"]
        self.name: str = rule_cfg["name"]
        self.action: str = rule_cfg["action"]
        self.reason_code: str = rule_cfg["reason_code"]
        self._condition: Dict[str, Any] = rule_cfg["condition"]

        # Validate at load time — fail-hard on bad rule config
        try:
            validate_rule(self._condition)
        except PolicyDSLError as exc:
            raise ValueError(
                f"Rule {self.rule_id!r} ({self.name!r}) has an invalid DSL condition: {exc}"
            ) from exc

    def matches(self, ctx: Dict[str, Any]) -> bool:
        """Evaluate the DSL condition against *ctx* without eval()."""
        try:
            return evaluate_rule(self._condition, ctx, rule_id=self.rule_id)
        except Exception:  # noqa: BLE001
            return False


# ---------------------------------------------------------------------------
# DecisionEngineAgent
# ---------------------------------------------------------------------------


class DecisionEngineAgent(BaseAgent):
    """
    Config-driven decision engine: hard rules → model cutoffs → FCRA reason codes.

    Config keys (agent_config.yaml → decision_engine):
      hard_rules[], score_cutoffs, approved_term_months,
      enable_challenger, challenger_traffic_pct, policy_version
    """

    name = "DecisionEngineAgent"

    # FCRA adverse action descriptions
    _REASON_TEXT: Dict[str, str] = {
        "AA01": "High probability of default based on credit profile",
        "AA02": "Fraud or identity risk indicators detected",
        "AA03": "Insufficient credit history or no open accounts",
        "AA04": "Debt-to-income ratio exceeds policy limits",
        "AA05": "Application flagged for manual underwriter review",
    }

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self._policy_version: str = self.config.get("policy_version", "v1")
        self._cutoffs = self.config.get("score_cutoffs", {
            "approve_max_pd": 0.05,
            "review_max_pd": 0.10,
        })
        self._approved_term: int = self.config.get("approved_term_months", 36)
        self._hard_rules: List[HardRule] = [
            HardRule(r) for r in self.config.get("hard_rules", [])
        ]

    def _apply_hard_rules(
        self, ctx: Dict[str, Any]
    ) -> Tuple[Optional[DecisionLabel], List[str]]:
        """
        Returns (decision_label, [reason_codes]) if a hard rule fires,
        else (None, []).
        """
        for rule in self._hard_rules:
            if rule.matches(ctx):
                label = DecisionLabel(rule.action)
                return label, [rule.reason_code]
        return None, []

    def _decide_single(
        self, score: ModelScores, ctx: Dict[str, Any], experiment_id: Optional[str],
        tenant_id: str = "",
    ) -> CreditDecision:
        t0 = time.perf_counter()

        # Merge score flags into context for rule evaluation
        ctx["fraud_flag"] = score.fraud_flag
        ctx["pd_score"] = score.pd_score

        # 1. Hard rules take priority (P0.3 will make these eval-free)
        decision, reason_codes = self._apply_hard_rules(ctx)

        if decision is None:
            # 2. No hard rule fired — delegate to credit_core.policy for the
            #    canonical score-based + fraud-flag decision logic.  This is
            #    the single source of truth shared with the Decision API.
            scores_row = pd.DataFrame([{
                "application_id": score.application_id,
                "pd_score": score.pd_score,
                "pd_band": score.pd_band.value if hasattr(score.pd_band, "value") else str(score.pd_band),
                "fraud_probability": score.fraud_probability,
                "fraud_flag": score.fraud_flag.value if hasattr(score.fraud_flag, "value") else str(score.fraud_flag),
            }])
            context_row = pd.DataFrame([{
                "application_id": score.application_id,
                **ctx,
            }])
            policy_results = evaluate_policy(
                scores_row,
                context_row,
                policy_version=self._policy_version,
            )
            pr = policy_results[0] if policy_results else None
            if pr is not None:
                decision = DecisionLabel(pr.decision)
                reason_codes = list(pr.reason_codes)
            else:
                decision = DecisionLabel.REJECT
                reason_codes = ["AA01"]

        # Deduplicate while preserving order
        seen: set = set()
        reason_codes = [c for c in reason_codes if not (c in seen or seen.add(c))]  # type: ignore

        latency_ms = (time.perf_counter() - t0) * 1000

        # Build approved product terms for approvals
        approved_amount: Optional[float] = None
        approved_rate: Optional[float] = None
        approved_term: Optional[int] = None
        if decision == DecisionLabel.APPROVE:
            approved_amount = ctx.get("loan_amount")
            approved_rate = score.recommended_rate
            approved_term = self._approved_term

        return CreditDecision(
            application_id=score.application_id,
            tenant_id=tenant_id,
            decision=decision,
            reason_codes=reason_codes,
            approved_amount=approved_amount,
            approved_rate=approved_rate,
            approved_term_months=approved_term,
            experiment_id=experiment_id,
            policy_version=self._policy_version,
            decision_latency_ms=round(latency_ms, 3),
        )

    # ------------------------------------------------------------------
    # Core agent logic
    # ------------------------------------------------------------------

    def _run(self, inputs: Dict[str, Any]) -> AgentResult:
        """
        inputs expected keys:
          "model_scores"  : List[dict]   — ModelScores dicts
          "validated"     : List[dict]   — ValidatedRecord dicts (for context)
          "experiment_id" : str | None   — active experiment ID
        """
        score_dicts: List[Dict[str, Any]] = inputs.get("model_scores", [])
        validated_dicts: List[Dict[str, Any]] = inputs.get("validated", [])
        experiment_id: Optional[str] = inputs.get("experiment_id")
        tenant_id: str = inputs.get("tenant_id", "")

        if not score_dicts:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILURE,
                errors=["No model_scores provided to DecisionEngineAgent"],
            )

        # Build context map: application_id → raw_features
        ctx_map: Dict[str, Dict[str, Any]] = {}
        for vr in validated_dicts:
            aid = vr.get("application_id", vr.get("raw_features", {}).get("application_id", ""))
            ctx_map[aid] = vr.get("raw_features", vr)

        decisions: List[CreditDecision] = []
        approve_count = reject_count = review_count = 0

        for sd in score_dicts:
            score = ModelScores(**sd)
            ctx = dict(ctx_map.get(score.application_id, {}))
            decision = self._decide_single(score, ctx, experiment_id, tenant_id=tenant_id)
            decisions.append(decision)

            if decision.decision == DecisionLabel.APPROVE:
                approve_count += 1
            elif decision.decision == DecisionLabel.REJECT:
                reject_count += 1
            else:
                review_count += 1

        n = len(decisions)
        self._log.info(
            "Decisions: APPROVE=%d (%.1f%%), REJECT=%d (%.1f%%), REVIEW=%d (%.1f%%)",
            approve_count, approve_count / max(n, 1) * 100,
            reject_count, reject_count / max(n, 1) * 100,
            review_count, review_count / max(n, 1) * 100,
        )

        return AgentResult(
            agent_name=self.name,
            status=AgentStatus.SUCCESS,
            payload={
                "decisions": [d.model_dump() for d in decisions],
                "stats": {
                    "total": n,
                    "approved": approve_count,
                    "rejected": reject_count,
                    "manual_review": review_count,
                    "approval_rate_pct": round(approve_count / max(n, 1) * 100, 2),
                },
            },
        )
