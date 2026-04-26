"""
tests/compliance/test_compliance_engine.py — Section 23.12
============================================================
Unit tests for ComplianceEngine.gate().

Test strategy:
  - BQ and compliance_data_plane are mocked so tests run offline.
  - Every code path in gate() is covered.
  - Zero-tolerance checks (SCRA, MLA) are separately verified.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Patch BigQuery and compliance data plane before importing engine
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_bq(monkeypatch):
    """Prevent any real BQ calls during unit tests."""
    monkeypatch.setattr("compliance.data_plane._BQ_AVAILABLE", False)
    monkeypatch.setattr("compliance.data_plane._bq", None)


FEDERAL_THRESHOLDS = {
    "MLA_MAPR_CAP/FEDERAL": 36.0,
    "SCRA_APR_CAP/FEDERAL": 6.0,
    "USURY_APR_MAX/CA": 36.0,
    "USURY_APR_MAX/TX": 100.0,   # TX has no statutory cap for state-chartered banks
}


def _make_threshold(threshold_id: str, jurisdiction: str, value: float):
    from compliance.data_plane import RegulatoryThreshold

    return RegulatoryThreshold(
        threshold_id=threshold_id,
        regulation="TEST",
        jurisdiction=jurisdiction,
        threshold_type="APR_MAX_PCT",
        threshold_value=value,
        legal_citation="Test citation",
    )


def _gate_kwargs(**overrides) -> dict:
    base = dict(
        source_system="cc_origination_policy",
        apr_assigned=24.99,
        state="CA",
        is_active_military=False,
        is_covered_borrower=False,
        proposed_action="ACQUIRE",
        applicant_id_hash="deadbeef" * 8,
        decision_id="dec-001",
        policy_version_id="v1.0.0",
    )
    base.update(overrides)
    return base


class TestComplianceEngineGate:
    """All tests for ComplianceEngine.gate()."""

    def setup_method(self):
        from compliance.engine import ComplianceEngine

        self.engine = ComplianceEngine()

    def _patch_all_thresholds(self):
        """Return a mock get_threshold that resolves from FEDERAL_THRESHOLDS."""
        from compliance.data_plane import RegulatoryThreshold

        def _get_threshold(threshold_id: str, jurisdiction: str = "FEDERAL"):
            key = f"{threshold_id}/{jurisdiction}"
            if key in FEDERAL_THRESHOLDS:
                return _make_threshold(threshold_id, jurisdiction, FEDERAL_THRESHOLDS[key])
            from compliance.data_plane import ComplianceDataPlaneError
            raise ComplianceDataPlaneError(f"No threshold for {threshold_id}/{jurisdiction}")

        return _get_threshold

    def test_all_checks_pass_standard_applicant(self, monkeypatch):
        monkeypatch.setattr("compliance.engine.get_threshold", self._patch_all_thresholds())
        monkeypatch.setattr(
            "compliance.engine._log_sync", lambda **_: "evt-1"
        )
        result = self.engine.gate(**_gate_kwargs(apr_assigned=24.99, state="CA"))

        assert result.passed is True
        assert result.override == "NONE"
        assert result.compliance_block is False
        assert len(result.blocking_checks) == 0

    def test_usury_cap_blocked(self, monkeypatch):
        monkeypatch.setattr("compliance.engine.get_threshold", self._patch_all_thresholds())
        monkeypatch.setattr("compliance.engine._log_sync", lambda **_: "evt-1")

        # CA cap = 36 %; assign APR 40 %
        result = self.engine.gate(**_gate_kwargs(apr_assigned=40.0, state="CA"))

        assert result.passed is False
        assert result.override == "MANUAL_REVIEW"
        assert result.compliance_block is True
        assert any("usury_cap_CA" in c for c in result.blocking_checks)

    def test_scra_apr_cap_blocked(self, monkeypatch):
        monkeypatch.setattr("compliance.engine.get_threshold", self._patch_all_thresholds())
        monkeypatch.setattr("compliance.engine._log_sync", lambda **_: "evt-1")

        # Active military, APR 8 % > SCRA cap 6 %
        result = self.engine.gate(
            **_gate_kwargs(
                apr_assigned=8.0,
                is_active_military=True,
                state="TX",  # TX has no usury cap at 36
            )
        )

        assert result.passed is False
        assert "scra_apr_cap" in " ".join(result.blocking_checks)

    def test_mla_mapr_cap_blocked(self, monkeypatch):
        monkeypatch.setattr("compliance.engine.get_threshold", self._patch_all_thresholds())
        monkeypatch.setattr("compliance.engine._log_sync", lambda **_: "evt-1")

        # Covered borrower, MAPR 40 % > MLA cap 36 %
        result = self.engine.gate(
            **_gate_kwargs(
                apr_assigned=40.0,
                is_covered_borrower=True,
                state="TX",
            )
        )

        assert result.passed is False
        assert "mla_mapr_cap" in " ".join(result.blocking_checks)

    def test_scra_apr_increase_prohibited(self, monkeypatch):
        monkeypatch.setattr("compliance.engine.get_threshold", self._patch_all_thresholds())
        monkeypatch.setattr("compliance.engine._log_sync", lambda **_: "evt-1")

        result = self.engine.gate(
            **_gate_kwargs(
                proposed_action="APR_UP",
                is_active_military=True,
                apr_assigned=4.0,  # under cap — SCRA APR increase is still blocked
                state="TX",
            )
        )

        assert result.passed is False
        assert any("scra_apr_increase_prohibition" in c for c in result.blocking_checks)

    def test_usury_cap_warn_when_no_threshold(self, monkeypatch):
        """State with no threshold entry -> WARN not BLOCKED."""
        from compliance.data_plane import ComplianceDataPlaneError

        def _no_threshold(threshold_id, jurisdiction="FEDERAL"):
            if jurisdiction == "FEDERAL":
                return _make_threshold(threshold_id, "FEDERAL", 36.0)
            raise ComplianceDataPlaneError(f"No threshold for {threshold_id}/{jurisdiction}")

        monkeypatch.setattr("compliance.engine.get_threshold", _no_threshold)
        monkeypatch.setattr("compliance.engine._log_sync", lambda **_: "evt-1")

        result = self.engine.gate(**_gate_kwargs(apr_assigned=100.0, state="ND"))

        # Should warn, not block — ND threshold unknown
        assert result.passed is True
        assert any("ND" in w for w in result.warn_checks)

    def test_multiple_blocking_checks(self, monkeypatch):
        monkeypatch.setattr("compliance.engine.get_threshold", self._patch_all_thresholds())
        monkeypatch.setattr("compliance.engine._log_sync", lambda **_: "evt-1")

        # Active military + covered borrower + APR 40 % > all caps
        result = self.engine.gate(
            **_gate_kwargs(
                apr_assigned=40.0,
                state="CA",
                is_active_military=True,
                is_covered_borrower=True,
                proposed_action="APR_UP",
            )
        )

        assert result.passed is False
        assert len(result.blocking_checks) >= 3

    def test_gate_never_raises(self, monkeypatch):
        """gate() must not propagate unexpected exceptions."""

        def _raise(*args, **kwargs):
            raise RuntimeError("Unexpected BQ error")

        monkeypatch.setattr("compliance.engine.get_threshold", _raise)
        monkeypatch.setattr("compliance.engine._log_sync", lambda **_: "evt-1")

        result = self.engine.gate(**_gate_kwargs())

        assert result.passed is False
        assert result.override == "MANUAL_REVIEW"
        assert "gate_error" in " ".join(result.blocking_checks)

    def test_non_military_skips_scra(self, monkeypatch):
        """SCRA check must be skipped for non-military applicants."""
        calls = []
        original = self._patch_all_thresholds()

        def _tracking_get(threshold_id, jurisdiction="FEDERAL"):
            calls.append(threshold_id)
            return original(threshold_id, jurisdiction)

        monkeypatch.setattr("compliance.engine.get_threshold", _tracking_get)
        monkeypatch.setattr("compliance.engine._log_sync", lambda **_: "evt-1")

        self.engine.gate(**_gate_kwargs(is_active_military=False))

        assert "SCRA_APR_CAP" not in calls

    def test_non_covered_borrower_skips_mla(self, monkeypatch):
        """MLA check must be skipped for non-covered borrowers."""
        calls = []
        original = self._patch_all_thresholds()

        def _tracking_get(threshold_id, jurisdiction="FEDERAL"):
            calls.append(threshold_id)
            return original(threshold_id, jurisdiction)

        monkeypatch.setattr("compliance.engine.get_threshold", _tracking_get)
        monkeypatch.setattr("compliance.engine._log_sync", lambda **_: "evt-1")

        self.engine.gate(**_gate_kwargs(is_covered_borrower=False))

        assert "MLA_MAPR_CAP" not in calls

    def test_compliance_event_ids_collected(self, monkeypatch):
        """Every executed check must append an event_id to
        compliance_event_ids."""
        monkeypatch.setattr("compliance.engine.get_threshold", self._patch_all_thresholds())

        counter = {"n": 0}

        def _log(**kwargs):
            counter["n"] += 1
            return f"evt-{counter['n']}"

        monkeypatch.setattr("compliance.engine._log_sync", _log)

        # Use is_covered_borrower=True so both usury_cap + mla_mapr checks log events
        result = self.engine.gate(**_gate_kwargs(is_covered_borrower=True, apr_assigned=24.99))
        # Usury check + MLA MAPR check = at least 2 events
        assert len(result.compliance_event_ids) >= 2
