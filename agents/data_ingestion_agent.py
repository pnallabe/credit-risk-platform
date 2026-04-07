"""
Data Ingestion Agent
====================
Domain Owner : Data Engineering / Credit Operations
SR 11-7 Stage: Pre-pipeline data governance gate

Responsibilities
----------------
* Accept raw applicant JSON (single or batch)
* Validate against the canonical ApplicantInput schema
* Enforce business-level data quality rules (Great Expectations style)
* Flag thin-file applicants for alt-data enrichment
* Emit ValidatedRecord(s) to the downstream Feature Engineering Agent
* Quarantine records that exceed error threshold

Inputs  : List[dict] — raw applicant payloads
Outputs : AgentResult.payload["validated"] = List[ValidatedRecord]
          AgentResult.payload["quarantined"] = List[dict]
          AgentResult.payload["stats"] = ingestion_stats dict
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import pandas as pd
from pydantic import ValidationError

from agents.base import AgentResult, AgentStatus, BaseAgent
from schemas.contracts import ApplicantInput, ValidatedRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation Rule Engine  (Great-Expectations-style, no hard dependency)
# ---------------------------------------------------------------------------


class ValidationRule:
    """Lightweight data-quality rule applied to a single row."""

    def __init__(
        self,
        rule_id: str,
        description: str,
        check_fn,
        severity: str = "error",  # "error" | "warning"
    ):
        self.rule_id = rule_id
        self.description = description
        self.check_fn = check_fn
        self.severity = severity

    def evaluate(self, record: ApplicantInput) -> tuple[bool, str]:
        """Returns (passed, message)."""
        try:
            passed = self.check_fn(record)
            return passed, "" if passed else f"[{self.rule_id}] {self.description}"
        except Exception as exc:  # noqa: BLE001
            return False, f"[{self.rule_id}] Rule evaluation error: {exc}"


def _build_default_rules(cfg: Dict[str, Any]) -> List[ValidationRule]:
    """Build the default ruleset from agent_config.yaml settings."""
    return [
        # ── Completeness rules ──────────────────────────────────────────────
        ValidationRule(
            "DQ-001",
            "annual_income must be positive",
            lambda r: r.annual_income > 0,
            severity="error",
        ),
        ValidationRule(
            "DQ-002",
            "loan_amount must be within policy bounds",
            lambda r: cfg.get("loan_amount_min", 500)
            <= r.loan_amount
            <= cfg.get("loan_amount_max", 300_000),
            severity="error",
        ),
        ValidationRule(
            "DQ-003",
            "loan_term_months must be 6-360",
            lambda r: 6 <= r.loan_term_months <= 360,
            severity="error",
        ),
        # ── Plausibility rules ──────────────────────────────────────────────
        ValidationRule(
            "DQ-004",
            "DTI warning when > 65%",
            lambda r: (r.dti or 0) <= cfg.get("dti_warning_threshold", 0.65),
            severity="warning",
        ),
        ValidationRule(
            "DQ-005",
            "annual_income within plausible range",
            lambda r: cfg.get("annual_income_min", 1_200)
            <= r.annual_income
            <= cfg.get("annual_income_max", 5_000_000),
            severity="warning",
        ),
        ValidationRule(
            "DQ-006",
            "employer_tenure_months should not exceed 600",
            lambda r: (r.employer_tenure_months or 0) <= 600,
            severity="warning",
        ),
        # ── Thin-file detection ─────────────────────────────────────────────
        ValidationRule(
            "DQ-007",
            "credit_score present (thin-file flag if absent)",
            lambda r: r.credit_score is not None,
            severity="warning",  # warning only — thin-file is handled, not rejected
        ),
    ]


# ---------------------------------------------------------------------------
# DataIngestionAgent
# ---------------------------------------------------------------------------


class DataIngestionAgent(BaseAgent):
    """
    Ingestion gate: validates + normalises raw applicant payloads.

    Config keys consumed from agent_config.yaml → data_ingestion:
      loan_amount_min, loan_amount_max, annual_income_min, annual_income_max,
      dti_warning_threshold, quarantine_error_threshold_pct, thin_file_missing_fields
    """

    name = "DataIngestionAgent"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self._rules = _build_default_rules(self.config)
        self._thin_file_fields: List[str] = self.config.get(
            "thin_file_missing_fields", ["credit_score", "num_open_accounts"]
        )
        self._quarantine_pct: float = self.config.get(
            "quarantine_error_threshold_pct", 0.10
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_thin_file(self, record: ApplicantInput) -> bool:
        """True when any thin-file sentinel fields are null."""
        return any(
            getattr(record, f, None) is None for f in self._thin_file_fields
        )

    def _validate_single(self, raw: Dict[str, Any]) -> ValidatedRecord:
        """Run schema + business-rule validation on one raw payload."""
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Schema validation via Pydantic
        try:
            record = ApplicantInput(**raw)
        except ValidationError as exc:
            return ValidatedRecord(
                application_id=raw.get("application_id", "UNKNOWN"),
                raw_features=raw,
                validation_passed=False,
                validation_errors=[str(exc)],
                source=raw.get("channel", "api"),
            )

        # 2. Business rule evaluation
        for rule in self._rules:
            passed, msg = rule.evaluate(record)
            if not passed:
                if rule.severity == "error":
                    errors.append(msg)
                else:
                    warnings.append(msg)

        # 3. Thin-file tagging
        thin = self._is_thin_file(record)
        if thin:
            warnings.append("DQ-THIN: Applicant classified as thin-file — alt-data signals will be used")

        return ValidatedRecord(
            application_id=record.application_id,
            raw_features=record.model_dump(),
            validation_passed=len(errors) == 0,
            validation_errors=errors,
            validation_warnings=warnings,
            source=raw.get("channel", "api"),
        )

    # ------------------------------------------------------------------
    # Core agent logic
    # ------------------------------------------------------------------

    def _run(self, inputs: Dict[str, Any]) -> AgentResult:
        """
        inputs expected keys:
          "records" : List[dict]   — raw applicant payloads
          "source"  : str          — optional source tag (default "api")
        """
        raw_records: List[Dict[str, Any]] = inputs.get("records", [])
        source: str = inputs.get("source", "api")

        if not raw_records:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILURE,
                errors=["No records provided to DataIngestionAgent"],
            )

        validated: List[ValidatedRecord] = []
        quarantined: List[Dict[str, Any]] = []
        warn_count = error_count = thin_count = 0

        for raw in raw_records:
            raw["channel"] = raw.get("channel", source)
            vr = self._validate_single(raw)
            if vr.validation_passed:
                validated.append(vr)
            else:
                quarantined.append(
                    {"raw": raw, "errors": vr.validation_errors}
                )
                error_count += 1
            warn_count += len(vr.validation_warnings)
            if "DQ-THIN" in " ".join(vr.validation_warnings):
                thin_count += 1

        total = len(raw_records)
        error_pct = error_count / max(total, 1)

        stats = {
            "total_received": total,
            "validated_count": len(validated),
            "quarantined_count": len(quarantined),
            "warning_count": warn_count,
            "thin_file_count": thin_count,
            "error_rate_pct": round(error_pct * 100, 2),
        }

        self._log.info(
            "Ingestion stats: %s", stats
        )

        # Quarantine gate
        if error_pct > self._quarantine_pct:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.PARTIAL,
                payload={
                    "validated": [v.model_dump() for v in validated],
                    "quarantined": quarantined,
                    "stats": stats,
                },
                warnings=[
                    f"Error rate {error_pct:.1%} exceeds quarantine threshold "
                    f"{self._quarantine_pct:.1%}. Batch marked PARTIAL."
                ],
            )

        return AgentResult(
            agent_name=self.name,
            status=AgentStatus.SUCCESS,
            payload={
                "validated": [v.model_dump() for v in validated],
                "quarantined": quarantined,
                "stats": stats,
            },
        )

    # ------------------------------------------------------------------
    # Convenience: validate a DataFrame directly
    # ------------------------------------------------------------------

    def validate_dataframe(self, df: pd.DataFrame) -> AgentResult:
        """Entry point for batch pipeline: DataFrame → AgentResult."""
        records = df.to_dict(orient="records")
        return self.execute({"records": records, "source": "batch"})
