"""
data_contracts.registry
=========================
Schema registry for all credit-risk-platform data contracts.

Responsibilities
----------------
1. **Catalogue** — lists all published contracts with version and domain.
2. **JSON Schema export** — generates standard JSON Schema (draft-07) for
   any contract, suitable for sharing with external consumers.
3. **OpenAPI component export** — emits the #/components/schemas block that
   can be merged into the Decision API or Analytics API OpenAPI spec.
4. **Validation** — validates a raw dict against a named contract, returning
   structured errors.
5. **Changelog** — machine-readable log of contract changes across versions.

Usage
-----
>>> from data_contracts.registry import DataContractRegistry
>>> registry = DataContractRegistry()

# List all contracts
>>> for entry in registry.list_contracts():
...     print(entry["contract_name"], entry["domain"], entry["version"])

# Export JSON Schema
>>> schema = registry.export_json_schema("CreditDecisionV1")

# Export all schemas as an OpenAPI components block
>>> components = registry.export_openapi_components()

# Validate a payload
>>> errors = registry.validate("ApplicationSubmittedV1", raw_dict)
>>> if errors:
...     print("Validation failed:", errors)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

from data_contracts.v1.application import (
    ApplicantProfileV1,
    ApplicationSubmittedV1,
    ApplicationValidatedV1,
)
from data_contracts.v1.decisions import (
    CreditDecisionV1,
    DecisionExplanationV1,
    DecisionRecordV1,
    PricingTermsV1,
)
from data_contracts.v1.features import (
    FeatureDriftReportV1,
    FeatureVectorV1,
    ModelPerformanceSnapshotV1,
)
from data_contracts.v1.portfolio import (
    PortfolioSummaryV1,
    RollRateBucketV1,
    SegmentBreakdownV1,
    VintageCohortV1,
)
from data_contracts.v1.compliance import (
    AdverseActionNoticeV1,
    FairLendingFlagV1,
    HMDARecordV1,
    Metro2TradelineV1,
)
from data_contracts.v1.audit import (
    DecisionAuditRecordV1,
    ManualReviewRecordV1,
    ModelDeploymentAuditV1,
    PolicyChangeAuditV1,
)
from data_contracts.v1.events import (
    ApplicationSubmittedEvent,
    BatchCompleteEvent,
    DataContractEvent,
    DecisionMadeEvent,
    DriftAlertEvent,
    PolicyChangedEvent,
)


# ---------------------------------------------------------------------------
# Internal catalogue entry
# ---------------------------------------------------------------------------


class ContractEntry:
    """Metadata entry for a single contract in the registry."""

    __slots__ = ("contract_name", "domain", "spec_version", "model_class", "description")

    def __init__(
        self,
        contract_name: str,
        domain: str,
        spec_version: str,
        model_class: Type[BaseModel],
        description: str = "",
    ) -> None:
        self.contract_name = contract_name
        self.domain = domain
        self.spec_version = spec_version
        self.model_class = model_class
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_name": self.contract_name,
            "domain": self.domain,
            "spec_version": self.spec_version,
            "model_class": self.model_class.__name__,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class DataContractRegistry:
    """
    Central catalogue of all credit-risk-platform data contracts.

    Instantiate once and reuse — it is stateless after __init__.
    """

    _CATALOGUE: List[ContractEntry] = [
        # ---- Application ------------------------------------------------
        ContractEntry(
            "ApplicantProfileV1", "application", "1.0.0", ApplicantProfileV1,
            "Canonical applicant demographics and financial snapshot.",
        ),
        ContractEntry(
            "ApplicationSubmittedV1", "application", "1.0.0", ApplicationSubmittedV1,
            "Emitted when a credit application is received by the Decision API.",
        ),
        ContractEntry(
            "ApplicationValidatedV1", "application", "1.0.0", ApplicationValidatedV1,
            "Emitted after the data ingestion agent validates the application record.",
        ),
        # ---- Decisions --------------------------------------------------
        ContractEntry(
            "PricingTermsV1", "decisions", "1.0.0", PricingTermsV1,
            "Approved loan terms: amount, rate, term, credit limit, EL, and profit.",
        ),
        ContractEntry(
            "DecisionExplanationV1", "decisions", "1.0.0", DecisionExplanationV1,
            "SHAP-based explanation + Reg B adverse action codes for a decision.",
        ),
        ContractEntry(
            "CreditDecisionV1", "decisions", "1.0.0", CreditDecisionV1,
            "Final underwriting verdict: APPROVE | REJECT | MANUAL_REVIEW.",
        ),
        ContractEntry(
            "DecisionRecordV1", "decisions", "1.0.0", DecisionRecordV1,
            "Full decision bundle: CreditDecisionV1 + DecisionExplanationV1.",
        ),
        # ---- Features ---------------------------------------------------
        ContractEntry(
            "FeatureVectorV1", "features", "1.0.0", FeatureVectorV1,
            "Point-in-time feature snapshot for one application.",
        ),
        ContractEntry(
            "FeatureDriftReportV1", "features", "1.0.0", FeatureDriftReportV1,
            "Aggregate PSI/KS drift report for a production batch.",
        ),
        ContractEntry(
            "ModelPerformanceSnapshotV1", "features", "1.0.0", ModelPerformanceSnapshotV1,
            "Champion/challenger model AUC, Gini, KS, and business metrics snapshot.",
        ),
        # ---- Portfolio --------------------------------------------------
        ContractEntry(
            "VintageCohortV1", "portfolio", "1.0.0", VintageCohortV1,
            "Cumulative default / loss performance for one origination-month cohort.",
        ),
        ContractEntry(
            "RollRateBucketV1", "portfolio", "1.0.0", RollRateBucketV1,
            "Monthly delinquency bucket transition matrix.",
        ),
        ContractEntry(
            "SegmentBreakdownV1", "portfolio", "1.0.0", SegmentBreakdownV1,
            "Approval rate and profitability breakdown by segment.",
        ),
        ContractEntry(
            "PortfolioSummaryV1", "portfolio", "1.0.0", PortfolioSummaryV1,
            "Aggregate portfolio health snapshot for a reporting period.",
        ),
        # ---- Compliance -------------------------------------------------
        ContractEntry(
            "AdverseActionNoticeV1", "compliance", "1.0.0", AdverseActionNoticeV1,
            "FCRA/Reg B adverse action notice delivered to a denied applicant.",
        ),
        ContractEntry(
            "HMDARecordV1", "compliance", "1.0.0", HMDARecordV1,
            "HMDA Loan Application Register (LAR) record per Reg C.",
        ),
        ContractEntry(
            "Metro2TradelineV1", "compliance", "1.0.0", Metro2TradelineV1,
            "Monthly credit bureau tradeline in CDIA Metro 2 format.",
        ),
        ContractEntry(
            "FairLendingFlagV1", "compliance", "1.0.0", FairLendingFlagV1,
            "Disparate impact monitoring flag from BISG / 4-5ths rule analysis.",
        ),
        # ---- Audit ------------------------------------------------------
        ContractEntry(
            "DecisionAuditRecordV1", "audit", "1.0.0", DecisionAuditRecordV1,
            "Immutable end-to-end pipeline audit trail for one application.",
        ),
        ContractEntry(
            "PolicyChangeAuditV1", "audit", "1.0.0", PolicyChangeAuditV1,
            "Immutable log of every credit policy version transition.",
        ),
        ContractEntry(
            "ModelDeploymentAuditV1", "audit", "1.0.0", ModelDeploymentAuditV1,
            "Model deployment and champion promotion audit record.",
        ),
        ContractEntry(
            "ManualReviewRecordV1", "audit", "1.0.0", ManualReviewRecordV1,
            "Human credit analyst manual review outcome.",
        ),
        # ---- Events -----------------------------------------------------
        ContractEntry(
            "DataContractEvent", "events", "1.0.0", DataContractEvent,
            "Base event envelope for all streamed events.",
        ),
        ContractEntry(
            "ApplicationSubmittedEvent", "events", "1.0.0", ApplicationSubmittedEvent,
            "Typed event wrapper for application.submitted.",
        ),
        ContractEntry(
            "DecisionMadeEvent", "events", "1.0.0", DecisionMadeEvent,
            "Typed event wrapper for decision.approved | rejected | manual_review.",
        ),
        ContractEntry(
            "BatchCompleteEvent", "events", "1.0.0", BatchCompleteEvent,
            "Typed event wrapper for batch.complete.",
        ),
        ContractEntry(
            "DriftAlertEvent", "events", "1.0.0", DriftAlertEvent,
            "Typed event wrapper for model.drift_alert.",
        ),
        ContractEntry(
            "PolicyChangedEvent", "events", "1.0.0", PolicyChangedEvent,
            "Typed event wrapper for policy.changed | policy.activated.",
        ),
    ]

    def __init__(self) -> None:
        self._index: Dict[str, ContractEntry] = {
            e.contract_name: e for e in self._CATALOGUE
        }

    # ------------------------------------------------------------------
    # Catalogue queries
    # ------------------------------------------------------------------

    def list_contracts(
        self,
        domain: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return all registered contracts as dicts, optionally filtered by domain."""
        entries = self._CATALOGUE
        if domain:
            entries = [e for e in entries if e.domain == domain]
        return [e.to_dict() for e in entries]

    def get_model_class(self, contract_name: str) -> Type[BaseModel]:
        """Return the Pydantic model class for ``contract_name``.

        Raises ``KeyError`` if the contract is not registered.
        """
        if contract_name not in self._index:
            raise KeyError(
                f"Contract '{contract_name}' is not registered. "
                f"Available: {sorted(self._index.keys())}"
            )
        return self._index[contract_name].model_class

    # ------------------------------------------------------------------
    # JSON Schema export
    # ------------------------------------------------------------------

    def export_json_schema(
        self,
        contract_name: str,
        indent: int = 2,
    ) -> str:
        """Export the JSON Schema (draft-07) for ``contract_name`` as a string.

        The returned schema includes ``$schema``, ``title``, and ``description``
        fields and is suitable for sharing with external consumers.
        """
        model_class = self.get_model_class(contract_name)
        entry = self._index[contract_name]
        raw_schema = model_class.model_json_schema()
        raw_schema["$schema"] = "http://json-schema.org/draft-07/schema#"
        raw_schema.setdefault("title", contract_name)
        raw_schema.setdefault("description", entry.description)
        raw_schema["x-contract-version"] = entry.spec_version
        raw_schema["x-domain"] = entry.domain
        return json.dumps(raw_schema, indent=indent, default=str)

    def export_all_json_schemas(self, indent: int = 2) -> Dict[str, Any]:
        """Return a dict of {contract_name: json_schema_dict} for all contracts."""
        result: Dict[str, Any] = {}
        for name, entry in self._index.items():
            schema = entry.model_class.model_json_schema()
            schema["$schema"] = "http://json-schema.org/draft-07/schema#"
            schema.setdefault("title", name)
            schema.setdefault("description", entry.description)
            schema["x-contract-version"] = entry.spec_version
            schema["x-domain"] = entry.domain
            result[name] = schema
        return result

    # ------------------------------------------------------------------
    # OpenAPI components export
    # ------------------------------------------------------------------

    def export_openapi_components(self) -> Dict[str, Any]:
        """
        Return an OpenAPI 3.1 ``#/components/schemas`` block for all contracts.

        Merge this into the Decision API or Analytics API OpenAPI spec to
        expose contract schemas via ``/openapi.json``.
        """
        schemas: Dict[str, Any] = {}
        for name, entry in self._index.items():
            schemas[name] = entry.model_class.model_json_schema()
        return {"components": {"schemas": schemas}}

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(
        self,
        contract_name: str,
        data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Validate ``data`` against the named contract.

        Returns an empty list on success.
        Returns a list of error dicts on failure, each with:
          ``{"loc": <field path>, "msg": <message>, "type": <error type>}``
        """
        model_class = self.get_model_class(contract_name)
        try:
            model_class.model_validate(data)
            return []
        except ValidationError as exc:
            return [
                {
                    "loc": " → ".join(str(p) for p in e["loc"]),
                    "msg": e["msg"],
                    "type": e["type"],
                }
                for e in exc.errors()
            ]
