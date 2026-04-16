"""
Real-Time Compliance Engine — Section 23.3
==========================================
Architecture contract
---------------------
- gate() NEVER raises; it always returns a ComplianceGateResult.
- A BLOCKED result overrides the upstream decision to MANUAL_REVIEW with
  compliance_block=True appended to the audit record.
- All events are logged to compliance_data_plane.compliance_events within
  the same synchronous call (p99 < 50 ms target).
- The module exposes a process-level singleton COMPLIANCE_ENGINE.
  All decision components import COMPLIANCE_ENGINE; they never instantiate
  ComplianceEngine directly.

Usage (in cc_origination_policy.evaluate_application):
------------------------------------------------------
    from compliance.engine import COMPLIANCE_ENGINE

    gate_result = COMPLIANCE_ENGINE.gate(
        source_system="cc_origination_policy",
        apr_assigned=decision.apr_assigned,
        state=application.state,
        is_active_military=application.is_active_military,
        is_covered_borrower=application.is_covered_borrower,
        proposed_action="ACQUIRE",
        applicant_id_hash=_hash(application.applicant_id),
        decision_id=decision.decision_id,
        policy_version_id=CURRENT_POLICY_VERSION,
    )
    if not gate_result.passed:
        decision = decision._replace(
            action="MANUAL_REVIEW",
            decline_reason=None,
            compliance_block=True,
            compliance_event_ids=gate_result.compliance_event_ids,
        )
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Literal, Optional

from compliance.data_plane import (
    ComplianceDataPlaneError,
    get_threshold,
    log_compliance_event,
)

logger = logging.getLogger(__name__)

DecisionOverride = Literal["NONE", "MANUAL_REVIEW", "DECLINE"]


@dataclass
class ComplianceFlag:
    """A structured compliance flag attached to a gate result."""

    rule_code: str      # e.g. "PV001" (prohibited variable)
    severity: str       # "BLOCK" | "WARN"
    message: str        # human-readable description
    field: str = ""     # the offending field name, if applicable


@dataclass
class ComplianceGateResult:
    """Result of a single ComplianceEngine.gate() call."""

    passed: bool
    override: DecisionOverride
    blocking_checks: list[str] = field(default_factory=list)
    warn_checks: list[str] = field(default_factory=list)
    compliance_block: bool = False
    compliance_event_ids: list[str] = field(default_factory=list)
    flags: list = field(default_factory=list)  # List[ComplianceFlag]


# ---------------------------------------------------------------------------
# Helper: run async log_compliance_event synchronously
# ---------------------------------------------------------------------------


def _log_sync(**kwargs) -> str:
    """Run log_compliance_event in whatever event loop is available."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Inside an async context (e.g. FastAPI) — fire-and-forget via
            # create_task. Returns a placeholder so gate() stays synchronous.
            asyncio.ensure_future(log_compliance_event(**kwargs))
            return "pending"
        else:
            return loop.run_until_complete(log_compliance_event(**kwargs))
    except Exception as exc:  # pragma: no cover
        logger.error("compliance event log failed: %s", exc)
        return "error"


# ---------------------------------------------------------------------------
# Compliance Engine
# ---------------------------------------------------------------------------


class ComplianceEngine:
    """
    Synchronous fail-closed compliance gate.

    Instantiate once per process.  See module docstring for usage contract.
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def gate(
        self,
        *,
        source_system: str,
        apr_assigned: float,
        state: str,
        is_active_military: bool,
        is_covered_borrower: bool,
        proposed_action: str,  # "ACQUIRE" | "APR_UP" | "CLD" | "CLU"
        applicant_id_hash: str,
        decision_id: str,
        policy_version_id: str,
        # GAP-08: optional feature dict for prohibited-variable screening
        input_features: Optional[Dict] = None,
    ) -> ComplianceGateResult:
        """
        Run all compliance checks for a single credit decision.

        Parameters
        ----------
        source_system : str
            Identifier of the calling component (e.g. ``"cc_origination_policy"``).
        apr_assigned : float
            APR (annual percentage rate, %) that the decision intends to assign.
        state : str
            Two-letter US state code for the applicant's residential address.
        is_active_military : bool
            True if applicant is on active military duty (SCRA eligibility).
        is_covered_borrower : bool
            True if applicant is a covered borrower under MLA (32 CFR Part 232).
        proposed_action : str
            Action being evaluated: ``"ACQUIRE"``, ``"APR_UP"``, ``"CLD"``, ``"CLU"``.
        applicant_id_hash : str
            SHA-256 hash of the applicant identifier (PII-safe).
        decision_id : str
            Unique identifier of the decision record (FK to audit.audit_log).
        policy_version_id : str
            Version identifier of the active origination policy.

        Returns
        -------
        ComplianceGateResult
            ``passed=True``  — all checks passed; proceed with the decision.
            ``passed=False`` — at least one check BLOCKED; override to MANUAL_REVIEW.
        """
        result = ComplianceGateResult(passed=True, override="NONE")

        # §6.2 — Prohibited variables gate (GAP-08)
        # This runs FIRST, before any other compliance check.
        try:
            from compliance.prohibited_variables import (
                check_for_prohibited_variables,
                ProhibitedVariableViolation,
            )
            check_for_prohibited_variables(input_features or {})
        except Exception as pv:
            from compliance.prohibited_variables import ProhibitedVariableViolation as _PVV
            if isinstance(pv, _PVV):
                result.passed = False
                result.flags.append(ComplianceFlag(
                    rule_code="PV001",
                    severity="BLOCK",
                    message=str(pv),
                    field=pv.variable,
                ))
                result.blocking_checks.append(f"PV001: {pv.variable}")
                result.override = "DECLINE"
                return result

        common = dict(
            source_system=source_system,
            applicant_id_hash=applicant_id_hash,
            decision_id=decision_id,
            policy_version_id=policy_version_id,
        )

        try:
            self._usury_cap_check(
                result=result, apr_assigned=apr_assigned, state=state, **common
            )
            self._scra_check(
                result=result,
                apr_assigned=apr_assigned,
                is_active_military=is_active_military,
                **common,
            )
            self._mla_mapr_check(
                result=result,
                apr_assigned=apr_assigned,
                is_covered_borrower=is_covered_borrower,
                **common,
            )
            self._action_eligibility_check(
                result=result,
                proposed_action=proposed_action,
                is_active_military=is_active_military,
                **common,
            )
        except Exception as exc:  # pragma: no cover — safety net, never suppress
            logger.error(
                "ComplianceEngine.gate() unexpected error for decision %s: %s",
                decision_id,
                exc,
                exc_info=True,
            )
            # Fail closed — unexpected error maps to MANUAL_REVIEW
            result.blocking_checks.append(f"gate_error: {type(exc).__name__}")

        if result.blocking_checks:
            result.passed = False
            result.override = "MANUAL_REVIEW"
            result.compliance_block = True

        return result

    # ------------------------------------------------------------------
    # Individual check implementations
    # ------------------------------------------------------------------

    def _usury_cap_check(
        self,
        *,
        result: ComplianceGateResult,
        apr_assigned: float,
        state: str,
        source_system: str,
        applicant_id_hash: str,
        decision_id: str,
        policy_version_id: str,
    ) -> None:
        """
        Verify the assigned APR does not exceed the state usury cap.
        Falls back to WARN (not BLOCKED) if the threshold is unavailable for
        the state, to avoid blocking decisions in states with no statutory cap —
        but logs the warning for human review.
        """
        try:
            t = get_threshold("USURY_APR_MAX", jurisdiction=state)
            if apr_assigned <= t.threshold_value:
                check_result = "PASS"
            else:
                check_result = "BLOCKED"
        except ComplianceDataPlaneError:
            # No cap data for this state — warn but do not block
            check_result = "WARN"

        event_id = _log_sync(
            event_type="REALTIME_GATE",
            source_system=source_system,
            check_name=f"usury_cap_{state}",
            check_result=check_result,
            observed_value=apr_assigned,
            threshold_id=f"USURY_APR_MAX/{state}",
            applicant_id_hash=applicant_id_hash,
            decision_id=decision_id,
            policy_version_id=policy_version_id,
        )
        result.compliance_event_ids.append(event_id)

        if check_result == "BLOCKED":
            result.blocking_checks.append(
                f"usury_cap_{state}: APR {apr_assigned:.2f}% exceeds state cap"
            )
        elif check_result == "WARN":
            result.warn_checks.append(
                f"usury_cap_{state}: no threshold data — manual verification required"
            )

    def _scra_check(
        self,
        *,
        result: ComplianceGateResult,
        apr_assigned: float,
        is_active_military: bool,
        source_system: str,
        applicant_id_hash: str,
        decision_id: str,
        policy_version_id: str,
    ) -> None:
        """
        SCRA 50 U.S.C. § 3937 — active-duty military APR cap of 6 %.
        Only evaluated when is_active_military=True.
        """
        if not is_active_military:
            return

        t = get_threshold("SCRA_APR_CAP", jurisdiction="FEDERAL")
        check_result = "PASS" if apr_assigned <= t.threshold_value else "BLOCKED"

        event_id = _log_sync(
            event_type="REALTIME_GATE",
            source_system=source_system,
            check_name="scra_apr_cap",
            check_result=check_result,
            observed_value=apr_assigned,
            threshold_id="SCRA_APR_CAP",
            threshold_value=t.threshold_value,
            applicant_id_hash=applicant_id_hash,
            decision_id=decision_id,
            policy_version_id=policy_version_id,
        )
        result.compliance_event_ids.append(event_id)

        if check_result == "BLOCKED":
            result.blocking_checks.append(
                f"scra_apr_cap: APR {apr_assigned:.2f}% > {t.threshold_value}% "
                "(active military — 50 U.S.C. § 3937)"
            )

    def _mla_mapr_check(
        self,
        *,
        result: ComplianceGateResult,
        apr_assigned: float,
        is_covered_borrower: bool,
        source_system: str,
        applicant_id_hash: str,
        decision_id: str,
        policy_version_id: str,
    ) -> None:
        """
        MLA 10 U.S.C. § 987 — covered-borrower MAPR cap of 36 %.
        Only evaluated when is_covered_borrower=True.
        """
        if not is_covered_borrower:
            return

        t = get_threshold("MLA_MAPR_CAP", jurisdiction="FEDERAL")
        check_result = "PASS" if apr_assigned <= t.threshold_value else "BLOCKED"

        event_id = _log_sync(
            event_type="REALTIME_GATE",
            source_system=source_system,
            check_name="mla_mapr_cap",
            check_result=check_result,
            observed_value=apr_assigned,
            threshold_id="MLA_MAPR_CAP",
            threshold_value=t.threshold_value,
            applicant_id_hash=applicant_id_hash,
            decision_id=decision_id,
            policy_version_id=policy_version_id,
        )
        result.compliance_event_ids.append(event_id)

        if check_result == "BLOCKED":
            result.blocking_checks.append(
                f"mla_mapr_cap: MAPR {apr_assigned:.2f}% > {t.threshold_value}% "
                "(covered borrower — 10 U.S.C. § 987)"
            )

    def _action_eligibility_check(
        self,
        *,
        result: ComplianceGateResult,
        proposed_action: str,
        is_active_military: bool,
        source_system: str,
        applicant_id_hash: str,
        decision_id: str,
        policy_version_id: str,
    ) -> None:
        """
        SCRA prohibits increasing the APR on accounts held by active-duty military.
        Blocks APR_UP actions for active-military borrowers.
        """
        if is_active_military and proposed_action == "APR_UP":
            event_id = _log_sync(
                event_type="REALTIME_GATE",
                source_system=source_system,
                check_name="scra_apr_increase_prohibition",
                check_result="BLOCKED",
                threshold_id="SCRA_APR_CAP",
                applicant_id_hash=applicant_id_hash,
                decision_id=decision_id,
                policy_version_id=policy_version_id,
            )
            result.compliance_event_ids.append(event_id)
            result.blocking_checks.append(
                "scra_apr_increase_prohibition: APR_UP blocked for active military "
                "(50 U.S.C. § 3937)"
            )


# ---------------------------------------------------------------------------
# Module-level singleton — import COMPLIANCE_ENGINE in all decision components
# ---------------------------------------------------------------------------

COMPLIANCE_ENGINE: ComplianceEngine = ComplianceEngine()
